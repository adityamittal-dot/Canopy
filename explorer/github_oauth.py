"""Minimal "sign in with GitHub" OAuth flow - identity only, no scopes
requested and no per-user access token ever stored. Also fetches the
dashboard's repo list, from GitHub's *public* `/users/<username>/repos`
API - that endpoint needs no auth at all (it's the same data anyone gets
browsing the user's public profile), so listing repos never touches, and
never needs, anything from the OAuth exchange above. Together this means
there's nothing sensitive to protect once login is done: a stolen DB row
here reveals a github id/username/avatar, never a way to act as that user
on GitHub or to see anything private.

Kept as a small set of pure(ish) functions - each one HTTP call in, parsed
result out - the same shape as explorer/github_links.py, so both the OAuth
exchange and the repo-list fetch are unit-testable without a real GitHub
App, a browser, or the network.
"""

import os
import secrets
from urllib.parse import urlencode

import requests
from django.conf import settings

_AUTHORIZE_URL = 'https://github.com/login/oauth/authorize'
_TOKEN_URL = 'https://github.com/login/oauth/access_token'
_USER_URL = 'https://api.github.com/user'
_PUBLIC_REPOS_URL = 'https://api.github.com/users/{username}/repos'
_REQUEST_TIMEOUT_SECONDS = 10
_MAX_REPOS = 100


class GitHubOAuthError(Exception):
    """Raised when the OAuth exchange or the follow-up identity fetch fails."""


def new_state() -> str:
    """A random, unguessable value stashed in the session and round-tripped
    through GitHub - the standard OAuth CSRF guard against a forged callback
    (someone else's authorization code being handed to a victim's session)."""
    return secrets.token_urlsafe(32)


def build_authorize_url(redirect_uri: str, state: str) -> str:
    """No `scope` param at all - GitHub treats an absent scope as
    read-only identity access (the same as visiting someone's public
    profile), which is all a login needs."""
    params = {
        'client_id': settings.GITHUB_OAUTH_CLIENT_ID,
        'redirect_uri': redirect_uri,
        'state': state,
    }
    return f'{_AUTHORIZE_URL}?{urlencode(params)}'


def exchange_code_for_token(code: str, redirect_uri: str) -> str:
    """Trades a one-time authorization `code` for an access token. The
    token returned here is used once, immediately, to fetch the caller's
    identity below - it is never written to the database or session."""
    try:
        response = requests.post(
            _TOKEN_URL,
            data={
                'client_id': settings.GITHUB_OAUTH_CLIENT_ID,
                'client_secret': settings.GITHUB_OAUTH_CLIENT_SECRET,
                'code': code,
                'redirect_uri': redirect_uri,
            },
            headers={'Accept': 'application/json'},
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise GitHubOAuthError(f'failed to reach GitHub for token exchange: {exc}') from exc

    data = response.json()
    token = data.get('access_token')
    if not token:
        raise GitHubOAuthError(data.get('error_description') or 'GitHub did not return an access token')
    return token


def fetch_github_identity(access_token: str) -> dict:
    """Returns {'id', 'login', 'avatar_url'} for the token's owner."""
    try:
        response = requests.get(
            _USER_URL,
            headers={'Authorization': f'Bearer {access_token}', 'Accept': 'application/vnd.github+json'},
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise GitHubOAuthError(f'failed to fetch GitHub identity: {exc}') from exc

    data = response.json()
    if 'id' not in data or 'login' not in data:
        raise GitHubOAuthError('unexpected response from GitHub while fetching identity')
    return {'id': data['id'], 'login': data['login'], 'avatar_url': data.get('avatar_url', '')}


def _repo_row(repo: dict) -> dict:
    return {
        'name': repo.get('name', ''),
        'full_name': repo.get('full_name', ''),
        'html_url': repo.get('html_url', ''),
        'description': repo.get('description') or '',
        'language': repo.get('language') or '',
        'stars': repo.get('stargazers_count', 0),
        'updated_at': repo.get('updated_at', ''),
        'fork': bool(repo.get('fork', False)),
    }


def fetch_public_repos(username: str) -> list[dict]:
    """The dashboard's repo table: every public repo `username` owns
    (forks included, flagged via the 'fork' key), most-recently-pushed
    first. Uses GitHub's public per-user
    endpoint (no auth required, same data as browsing their profile) -
    the optional GITHUB_TOKEN env var (already used by github_links.py for
    the source-snippet fetch) is sent along only to raise the shared rate
    limit, never because this needs any permission it grants. Returns []
    on any failure rather than raising - a dashboard that can't reach
    GitHub should show "no repos found", not a crashed page.
    """
    token = os.environ.get('GITHUB_TOKEN')
    headers = {'Accept': 'application/vnd.github+json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'

    try:
        response = requests.get(
            _PUBLIC_REPOS_URL.format(username=username),
            headers=headers,
            params={'type': 'owner', 'sort': 'pushed', 'per_page': _MAX_REPOS},
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        repos = response.json()
    except (requests.RequestException, ValueError):
        return []

    if not isinstance(repos, list):
        return []
    # This is the public per-user endpoint, so every result is already
    # public - the explicit check is a defensive backstop, not a real
    # filter, in case that ever changes. Forks stay in the list (still a
    # real, analyzable public repo) but are flagged so the template can
    # mark them.
    return [_repo_row(r) for r in repos if not r.get('private', False)]
