"""GitHub-specific deep links and source snippet fetching for the detail panel.

Deliberately scoped to github.com only - the app doesn't claim to support
any other host yet (see README's known limitations), so these functions
return None for a non-GitHub repo url rather than guessing at a URL shape
that wouldn't work.
"""

import functools
import os
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


@functools.lru_cache(maxsize=256)
def _fetch_raw_file(repo_url: str, commit_hash: str, relative_path: str, timeout: float = 5.0) -> str | None:
    """The network part of fetch_source_snippet, cached: content at a fixed
    commit hash is immutable, so the same (repo_url, commit_hash,
    relative_path) triple can never legitimately return different content -
    no staleness risk. A failed fetch (bad host, timeout, missing file) also
    gets cached as None for the rest of the process's lifetime rather than
    retried on every click; acceptable for a transient blip at MVP scale,
    but means a genuinely-flaky failure won't self-heal without a restart.
    """
    owner_repo = parse_github_owner_repo(repo_url)
    if owner_repo is None:
        return None
    owner, repo = owner_repo

    raw_url = f'https://raw.githubusercontent.com/{owner}/{repo}/{commit_hash}/{relative_path}'
    # Optional: an unauthenticated IP has a much lower allowance against
    # GitHub's raw-content host than an authenticated one. GITHUB_TOKEN
    # only needs public_repo (or no scopes at all) access.
    token = os.environ.get('GITHUB_TOKEN')
    headers = {'Authorization': f'Bearer {token}'} if token else {}
    try:
        response = requests.get(raw_url, headers=headers, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException:
        return None
    return response.text


def fetch_source_snippet(repo_url: str, commit_hash: str, relative_path: str,
                          lineno: int | None = None, end_lineno: int | None = None,
                          timeout: float = 5.0) -> str | None:
    """Fetch a file (or a line-range slice of it) from GitHub's raw content
    API. Returns None on any failure (non-GitHub url, network error, missing
    file) - the caller is expected to show a "source unavailable" fallback
    rather than treat this as fatal."""
    text = _fetch_raw_file(repo_url, commit_hash, relative_path, timeout)
    if text is None:
        return None

    if not lineno or not end_lineno or end_lineno < lineno:
        return text

    lines = text.splitlines()
    return '\n'.join(lines[lineno - 1:end_lineno])
