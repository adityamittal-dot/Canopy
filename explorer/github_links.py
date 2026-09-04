"""GitHub-specific deep links and source snippet fetching for the detail panel.

Deliberately scoped to github.com only - the app doesn't claim to support
any other host yet (see README's known limitations), so these functions
return None for a non-GitHub repo url rather than guessing at a URL shape
that wouldn't work.
"""

from urllib.parse import urlparse

import requests

_GITHUB_HOSTS = {'github.com', 'www.github.com'}


def parse_github_owner_repo(repo_url: str) -> tuple[str, str] | None:
    parsed = urlparse(repo_url)
    if parsed.hostname not in _GITHUB_HOSTS:
        return None

    parts = [p for p in parsed.path.split('/') if p]
    if len(parts) < 2:
        return None

    owner, repo = parts[0], parts[1]
    return owner, repo.removesuffix('.git')


def github_blob_url(repo_url: str, commit_hash: str, relative_path: str,
                     lineno: int | None = None, end_lineno: int | None = None) -> str | None:
    owner_repo = parse_github_owner_repo(repo_url)
    if owner_repo is None:
        return None
    owner, repo = owner_repo

    url = f'https://github.com/{owner}/{repo}/blob/{commit_hash}/{relative_path}'
    if lineno:
        url += f'#L{lineno}'
        if end_lineno and end_lineno != lineno:
            url += f'-L{end_lineno}'
    return url


def fetch_source_snippet(repo_url: str, commit_hash: str, relative_path: str,
                          lineno: int | None = None, end_lineno: int | None = None,
                          timeout: float = 5.0) -> str | None:
    """Fetch a file (or a line-range slice of it) from GitHub's raw content
    API. Returns None on any failure (non-GitHub url, network error, missing
    file) - the caller is expected to show a "source unavailable" fallback
    rather than treat this as fatal."""
    owner_repo = parse_github_owner_repo(repo_url)
    if owner_repo is None:
        return None
    owner, repo = owner_repo

    raw_url = f'https://raw.githubusercontent.com/{owner}/{repo}/{commit_hash}/{relative_path}'
    try:
        response = requests.get(raw_url, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException:
        return None

    if not lineno or not end_lineno or end_lineno < lineno:
        return response.text

    lines = response.text.splitlines()
    return '\n'.join(lines[lineno - 1:end_lineno])
