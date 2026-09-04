import ipaddress
import socket
from urllib.parse import urlparse

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import IntegrityError
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_http_methods

from parsing.clone import CloneError, get_remote_head_commit
from parsing.pipeline import analyze_repo

from .models import CommitAnalysis, Repo

_validate_url = URLValidator(schemes=['http', 'https'])

# Analysis clones a caller-supplied repo server-side, so it's a real
# resource-exhaustion vector without some limit - 5 submissions/minute per
# IP is generous for legitimate use (a cache hit on an already-analyzed
# repo doesn't even need this) but blocks a client from hammering the
# clone/parse pipeline.
#
# Uses Django's default cache (LocMemCache - process-local, no separate
# service to run), so this is only correctly enforced with a single
# gunicorn worker/replica, which is the deployed default (no --workers or
# WEB_CONCURRENCY set). Scaling to multiple workers or replicas would
# split traffic across processes that don't share this counter, silently
# multiplying the effective limit - move to a shared cache (e.g. Redis) if
# that becomes real.
_RATE_LIMIT_WINDOW_SECONDS = 60
_RATE_LIMIT_MAX_REQUESTS = 5


def _client_ip(request) -> str:
  # Railway (and most PaaS hosts) put the app behind a proxy, so the real
  # client address arrives via X-Forwarded-For rather than REMOTE_ADDR.
  forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
  if forwarded:
    return forwarded.split(',')[0].strip()
  return request.META.get('REMOTE_ADDR', 'unknown')


def _is_rate_limited(request) -> bool:
  key = f'analyze-rate:{_client_ip(request)}'
  count = cache.get(key, 0)
  if count >= _RATE_LIMIT_MAX_REQUESTS:
    return True
  cache.set(key, count + 1, timeout=_RATE_LIMIT_WINDOW_SECONDS)
  return False


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
    elif _is_rate_limited(request):
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
