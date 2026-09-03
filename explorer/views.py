from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from parsing.clone import CloneError, get_remote_head_commit
from parsing.pipeline import analyze_repo

from .models import CommitAnalysis, Repo

_validate_url = URLValidator(schemes=['http', 'https'])


def dash_test(request):
  return render(request, 'explorer/dash_test.html')


def _normalize_url(raw_url: str) -> str:
  return raw_url.strip().rstrip('/').removesuffix('.git')


def _derive_repo_name(url: str) -> str:
  candidate = url.rsplit('/', 1)[-1] or url
  if Repo.objects.filter(name=candidate).exists():
    candidate = url  # url is unique and unused so far, so this can never collide
  return candidate


def _get_or_create_repo(url: str) -> Repo:
  repo = Repo.objects.filter(url=url).first()
  if repo is not None:
    return repo
  return Repo.objects.create(url=url, name=_derive_repo_name(url))


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
    else:
      try:
        _validate_url(url)
      except ValidationError:
        context['error'] = f'"{url}" is not a valid http(s) URL.'
      else:
        context.update(_run_analysis(url))

  return render(request, 'explorer/analyze.html', context)
