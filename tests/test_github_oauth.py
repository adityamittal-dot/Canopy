from unittest.mock import MagicMock, patch

import pytest
import requests

from explorer import github_oauth


# --- new_state ---------------------------------------------------------------

def test_new_state_is_unique_each_call():
    assert github_oauth.new_state() != github_oauth.new_state()


def test_new_state_is_reasonably_long():
    assert len(github_oauth.new_state()) >= 32


# --- build_authorize_url -------------------------------------------------------

def test_build_authorize_url_includes_client_id_redirect_and_state(monkeypatch):
    monkeypatch.setattr(github_oauth.settings, 'GITHUB_OAUTH_CLIENT_ID', 'test-client-id')
    url = github_oauth.build_authorize_url('https://example.com/callback/', 'the-state')

    assert url.startswith('https://github.com/login/oauth/authorize?')
    assert 'client_id=test-client-id' in url
    assert 'state=the-state' in url
    assert 'callback' in url


def test_build_authorize_url_requests_no_scope(monkeypatch):
    monkeypatch.setattr(github_oauth.settings, 'GITHUB_OAUTH_CLIENT_ID', 'test-client-id')
    url = github_oauth.build_authorize_url('https://example.com/callback/', 'state')

    assert 'scope=' not in url


# --- exchange_code_for_token ---------------------------------------------------

def _mock_response(json_data, status_ok=True):
    response = MagicMock()
    response.json.return_value = json_data
    if status_ok:
        response.raise_for_status.return_value = None
    else:
        response.raise_for_status.side_effect = requests.HTTPError('boom')
    return response


def test_exchange_code_for_token_returns_the_access_token():
    with patch('explorer.github_oauth.requests.post', return_value=_mock_response({'access_token': 'abc123'})):
        token = github_oauth.exchange_code_for_token('some-code', 'https://example.com/callback/')

    assert token == 'abc123'


def test_exchange_code_for_token_raises_when_github_returns_no_token():
    with patch('explorer.github_oauth.requests.post', return_value=_mock_response({'error_description': 'bad code'})):
        with pytest.raises(github_oauth.GitHubOAuthError, match='bad code'):
            github_oauth.exchange_code_for_token('bad-code', 'https://example.com/callback/')


def test_exchange_code_for_token_raises_on_network_failure():
    with patch('explorer.github_oauth.requests.post', side_effect=requests.ConnectionError('down')):
        with pytest.raises(github_oauth.GitHubOAuthError):
            github_oauth.exchange_code_for_token('code', 'https://example.com/callback/')


# --- fetch_github_identity ------------------------------------------------------

def test_fetch_github_identity_returns_id_login_and_avatar():
    payload = {'id': 42, 'login': 'octocat', 'avatar_url': 'https://avatars.example/octocat.png'}
    with patch('explorer.github_oauth.requests.get', return_value=_mock_response(payload)):
        identity = github_oauth.fetch_github_identity('a-token')

    assert identity == {'id': 42, 'login': 'octocat', 'avatar_url': 'https://avatars.example/octocat.png'}


def test_fetch_github_identity_raises_on_unexpected_payload():
    with patch('explorer.github_oauth.requests.get', return_value=_mock_response({'unexpected': 'shape'})):
        with pytest.raises(github_oauth.GitHubOAuthError):
            github_oauth.fetch_github_identity('a-token')


def test_fetch_github_identity_raises_on_network_failure():
    with patch('explorer.github_oauth.requests.get', side_effect=requests.Timeout('slow')):
        with pytest.raises(github_oauth.GitHubOAuthError):
            github_oauth.fetch_github_identity('a-token')


# --- fetch_public_repos ---------------------------------------------------------

_SAMPLE_REPOS = [
    {
        'name': 'canopy', 'full_name': 'octocat/canopy', 'html_url': 'https://github.com/octocat/canopy',
        'description': 'a repo explorer', 'language': 'Python', 'stargazers_count': 12,
        'updated_at': '2026-08-01T10:00:00Z', 'fork': False, 'private': False,
    },
    {
        'name': 'forked-thing', 'full_name': 'octocat/forked-thing', 'html_url': 'https://github.com/octocat/forked-thing',
        'description': None, 'language': None, 'stargazers_count': 0,
        'updated_at': '2026-07-01T10:00:00Z', 'fork': True, 'private': False,
    },
    {
        'name': 'secret-project', 'full_name': 'octocat/secret-project', 'html_url': 'https://github.com/octocat/secret-project',
        'description': 'should never appear', 'language': 'Python', 'stargazers_count': 3,
        'updated_at': '2026-06-01T10:00:00Z', 'fork': False, 'private': True,
    },
]


def test_fetch_public_repos_maps_fields():
    with patch('explorer.github_oauth.requests.get', return_value=_mock_response(_SAMPLE_REPOS)):
        repos = github_oauth.fetch_public_repos('octocat')

    canopy = next(r for r in repos if r['name'] == 'canopy')
    assert canopy['full_name'] == 'octocat/canopy'
    assert canopy['stars'] == 12
    assert canopy['language'] == 'Python'
    assert canopy['fork'] is False


def test_fetch_public_repos_keeps_forks_but_flags_them():
    with patch('explorer.github_oauth.requests.get', return_value=_mock_response(_SAMPLE_REPOS)):
        repos = github_oauth.fetch_public_repos('octocat')

    fork = next(r for r in repos if r['name'] == 'forked-thing')
    assert fork['fork'] is True


def test_fetch_public_repos_excludes_private_repos_defensively():
    with patch('explorer.github_oauth.requests.get', return_value=_mock_response(_SAMPLE_REPOS)):
        repos = github_oauth.fetch_public_repos('octocat')

    assert all(r['name'] != 'secret-project' for r in repos)


def test_fetch_public_repos_returns_empty_list_on_network_failure():
    with patch('explorer.github_oauth.requests.get', side_effect=requests.ConnectionError('down')):
        assert github_oauth.fetch_public_repos('octocat') == []


def test_fetch_public_repos_returns_empty_list_on_unexpected_shape():
    with patch('explorer.github_oauth.requests.get', return_value=_mock_response({'not': 'a list'})):
        assert github_oauth.fetch_public_repos('octocat') == []


def test_fetch_public_repos_sends_optional_github_token(monkeypatch):
    monkeypatch.setenv('GITHUB_TOKEN', 'raise-my-limit')
    captured = {}

    def fake_get(url, headers=None, **kwargs):
        captured['headers'] = headers
        return _mock_response([])

    with patch('explorer.github_oauth.requests.get', side_effect=fake_get):
        github_oauth.fetch_public_repos('octocat')

    assert captured['headers']['Authorization'] == 'Bearer raise-my-limit'


def test_fetch_public_repos_omits_auth_header_without_a_token(monkeypatch):
    monkeypatch.delenv('GITHUB_TOKEN', raising=False)
    captured = {}

    def fake_get(url, headers=None, **kwargs):
        captured['headers'] = headers
        return _mock_response([])

    with patch('explorer.github_oauth.requests.get', side_effect=fake_get):
        github_oauth.fetch_public_repos('octocat')

    assert 'Authorization' not in captured['headers']
