import ipaddress
import socket
from urllib.parse import urlparse

from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import IntegrityError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from parsing.clone import CloneError, get_remote_head_commit
from parsing.pipeline import analyze_repo

from .github_oauth import GitHubOAuthError, build_authorize_url, exchange_code_for_token, fetch_github_identity, fetch_public_repos, new_state
from .models import CommitAnalysis, GitHubAccount, Repo
from .ratelimit import is_rate_limited

_validate_url = URLValidator(schemes=['http', 'https'])

# Analysis clones a caller-supplied repo server-side, so it's a real
# resource-exhaustion vector without some limit - 5 submissions/minute per
# IP is generous for legitimate use (a cache hit on an already-analyzed
# repo doesn't even need this) but blocks a client from hammering the
# clone/parse pipeline. See explorer/ratelimit.py for the (process-local
# cache, single-worker-only) mechanism this relies on.
_RATE_LIMIT_WINDOW_SECONDS = 60
_RATE_LIMIT_MAX_REQUESTS = 5


def dash_test(request):
  return render(request, 'explorer/dash_test.html')


def _normalize_url(raw_url: str) -> str:
  return raw_url.strip().rstrip('/').removesuffix('.git')


def _is_public_host(hostname: str) -> bool:
  """Reject hosts that resolve to private/loopback/link-local addresses.

  This is a check-time guard against the analyze view being used as an SSRF
  proxy (e.g. pointing it at 169.254.169.254 or an internal-network host).
  It does not protect against DNS rebinding between this check and the later
  git subprocess call actually connecting - closing that fully would require
  resolving the host once and forcing git to connect to that exact address,
  which isn't attempted here.
  """
  try:
    infos = socket.getaddrinfo(hostname, None)
  except socket.gaierror:
    return False

  for info in infos:
    ip = ipaddress.ip_address(info[4][0])
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
      return False

  return True


def _derive_repo_name(url: str) -> str:
  candidate = url.rsplit('/', 1)[-1] or url
  if Repo.objects.filter(name=candidate).exists():
    candidate = url  # url is unique and unused so far, so this can never collide
  return candidate


def _get_or_create_repo(url: str) -> Repo:
  repo = Repo.objects.filter(url=url).first()
  if repo is not None:
    return repo

  try:
    return Repo.objects.create(url=url, name=_derive_repo_name(url))
  except IntegrityError:
    # Lost a race against another request. If it was our url that got
    # created first, use that row. Otherwise the collision was on the
    # derived name instead (a different url) - url itself is still free,
    # so retry once with the url as the guaranteed-unique name.
    repo = Repo.objects.filter(url=url).first()
    if repo is not None:
      return repo
    return Repo.objects.create(url=url, name=url)


def _run_analysis(url: str) -> dict:
  try:
    head_commit_hash = get_remote_head_commit(url)
  except CloneError as exc:
    return {'error': str(exc)}

  repo = _get_or_create_repo(url)

  cached = CommitAnalysis.objects.filter(repo=repo, commit_hash=head_commit_hash).first()
  if cached is not None:
    return {'analysis': cached, 'created': False}

  try:
    result = analyze_repo(url)
  except CloneError as exc:
    return {'error': str(exc)}

  analysis, created = CommitAnalysis.objects.get_or_create(
    repo=repo,
    commit_hash=result['commit_hash'],
    defaults={'graph': result},
  )
  return {'analysis': analysis, 'created': created}


@require_http_methods(['GET', 'POST'])
def analyze(request):
  context = {}

  if request.method == 'POST':
    url = _normalize_url(request.POST.get('url', ''))
    context['url'] = url

    if not url:
      context['error'] = 'Enter a repo URL.'
    elif is_rate_limited(request, 'analyze-rate', _RATE_LIMIT_MAX_REQUESTS, _RATE_LIMIT_WINDOW_SECONDS):
      context['error'] = 'Too many requests - please wait a minute and try again.'
    else:
      try:
        _validate_url(url)
      except ValidationError:
        context['error'] = f'"{url}" is not a valid http(s) URL.'
      else:
        hostname = urlparse(url).hostname
        if not hostname or not _is_public_host(hostname):
          context['error'] = f'"{url}" does not resolve to a public host.'
        else:
          context.update(_run_analysis(url))

  return render(request, 'explorer/analyze.html', context)


def graph_view(request, analysis_id):
  analysis = get_object_or_404(CommitAnalysis.objects.select_related('repo'), pk=analysis_id)
  return render(request, 'explorer/graph.html', {
    'analysis': analysis,
    'initial_arguments': {'analysis-id-store': {'data': analysis.id}},
  })


# --- GitHub sign-in / dashboard ---------------------------------------------
# See explorer/github_oauth.py for why this never requests a scope or stores
# an access token - it's identity-only, and the dashboard's repo list comes
# from GitHub's public API afterward.

def _oauth_redirect_uri(request) -> str:
  return request.build_absolute_uri(reverse('github_callback'))


def github_login(request):
  state = new_state()
  request.session['github_oauth_state'] = state
  return redirect(build_authorize_url(_oauth_redirect_uri(request), state))


def _get_or_create_user_for_identity(identity: dict) -> User:
  """Race-safe get-or-create, mirroring _get_or_create_repo above: GitHub's
  own username is globally unique and this app's only signup path is this
  OAuth flow, so github_id (and the Django username mirroring it) can't
  legitimately collide with anything else - the IntegrityError fallback
  only matters if two requests for the same brand-new account land at once.
  """
  account = GitHubAccount.objects.filter(github_id=identity['id']).select_related('user').first()
  if account is not None:
    if account.username != identity['login'] or account.avatar_url != identity['avatar_url']:
      account.username = identity['login']
      account.avatar_url = identity['avatar_url']
      account.save(update_fields=['username', 'avatar_url'])
    return account.user

  try:
    user = User.objects.create_user(username=identity['login'])
    GitHubAccount.objects.create(
      user=user, github_id=identity['id'], username=identity['login'], avatar_url=identity['avatar_url'],
    )
    return user
  except IntegrityError:
    account = GitHubAccount.objects.filter(github_id=identity['id']).select_related('user').first()
    if account is None:
      raise
    return account.user


def github_callback(request):
  expected_state = request.session.pop('github_oauth_state', None)
  state = request.GET.get('state')
  code = request.GET.get('code')

  if not code or not state or not expected_state or state != expected_state:
    return render(request, 'explorer/analyze.html', {'error': 'GitHub sign-in failed - please try again.'})

  try:
    token = exchange_code_for_token(code, _oauth_redirect_uri(request))
    identity = fetch_github_identity(token)
  except GitHubOAuthError as exc:
    return render(request, 'explorer/analyze.html', {'error': f'GitHub sign-in failed: {exc}'})

  user = _get_or_create_user_for_identity(identity)
  auth_login(request, user)
  return redirect('dashboard')


def github_logout(request):
  auth_logout(request)
  return redirect('analyze')


@login_required
def dashboard(request):
  account = request.user.github_account
  repos = fetch_public_repos(account.username)
  return render(request, 'explorer/dashboard.html', {'account': account, 'repos': repos})
