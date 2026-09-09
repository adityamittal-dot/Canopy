from unittest.mock import MagicMock, patch

import pytest
from google.genai import errors as genai_errors

from explorer import ai_chat
from explorer.models import CommitAnalysis, Repo

GRAPH = {
    'nodes': [
        {'kind': 'module', 'name': 'app', 'docstring': None, 'relative_path': 'app.py', 'lineno': 1},
        {
            'kind': 'function', 'name': 'app.parse_config', 'docstring': 'Parses the config file.',
            'relative_path': 'app.py', 'lineno': 10,
        },
        {
            'kind': 'function', 'name': 'app.run_server', 'docstring': 'Starts the HTTP server.',
            'relative_path': 'app.py', 'lineno': 20,
        },
    ],
    'edges': [],
    'imports': {'app.py': []},
}


def _analysis():
    repo = Repo(name='demo-repo', url='https://github.com/example/demo-repo')
    return CommitAnalysis(repo=repo, commit_hash='a' * 40, graph=GRAPH)


# --- is_chat_enabled --------------------------------------------------------

def test_chat_disabled_when_no_api_key(monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    assert ai_chat.is_chat_enabled() is False


def test_chat_enabled_when_api_key_set(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'fake-key-for-testing')
    assert ai_chat.is_chat_enabled() is True


# --- build_repo_context ------------------------------------------------------

def test_context_includes_repo_identity():
    context = ai_chat.build_repo_context(_analysis(), 'what does this do')
    assert 'demo-repo' in context
    assert 'https://github.com/example/demo-repo' in context
    assert 'a' * 40 in context


def test_context_surfaces_relevant_symbols_for_keyword():
    context = ai_chat.build_repo_context(_analysis(), 'how does config parsing work?')
    assert 'parse_config' in context
    assert 'Parses the config file.' in context


def test_context_excludes_irrelevant_symbols():
    context = ai_chat.build_repo_context(_analysis(), 'how does config parsing work?')
    assert 'run_server' not in context


def test_context_stays_bounded_regardless_of_repo_size():
    big_graph = {
        'nodes': [
            {
                'kind': 'function', 'name': f'app.handler_{i}', 'docstring': 'Handles a request.',
                'relative_path': 'app.py', 'lineno': i,
            }
            for i in range(500)
        ],
        'edges': [], 'imports': {},
    }
    analysis = CommitAnalysis(repo=Repo(name='big', url='https://github.com/example/big'), commit_hash='b' * 40, graph=big_graph)

    context = ai_chat.build_repo_context(analysis, 'tell me about the request handlers')

    assert context.count('handler_') <= ai_chat._MAX_CONTEXT_SYMBOLS


# --- ask_about_repo -----------------------------------------------------------

def _mock_response(text):
    response = MagicMock()
    response.text = text
    return response


def test_ask_about_repo_returns_model_reply_text():
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = _mock_response('It parses a config file.')

    with patch.object(ai_chat, '_client', return_value=fake_client):
        reply = ai_chat.ask_about_repo(_analysis(), history=[], message='what does parse_config do?')

    assert reply == 'It parses a config file.'


def test_ask_about_repo_sends_system_instruction_and_context():
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = _mock_response('answer')

    with patch.object(ai_chat, '_client', return_value=fake_client):
        ai_chat.ask_about_repo(_analysis(), history=[], message='what does parse_config do?')

    _, kwargs = fake_client.models.generate_content.call_args
    assert kwargs['config'].system_instruction == ai_chat._SYSTEM_INSTRUCTION
    last_message = kwargs['contents'][-1]
    assert 'parse_config' in last_message.parts[0].text
    assert 'CONTEXT' in last_message.parts[0].text


def test_ask_about_repo_trims_history_to_max_turns():
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = _mock_response('answer')
    history = [{'role': 'user' if i % 2 == 0 else 'model', 'text': f'turn {i}'} for i in range(20)]

    with patch.object(ai_chat, '_client', return_value=fake_client):
        ai_chat.ask_about_repo(_analysis(), history=history, message='follow up')

    _, kwargs = fake_client.models.generate_content.call_args
    # trimmed history + the new message itself
    assert len(kwargs['contents']) == ai_chat._MAX_HISTORY_TURNS + 1


def test_ask_about_repo_caps_message_length():
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = _mock_response('answer')
    huge_message = 'x' * 5000

    with patch.object(ai_chat, '_client', return_value=fake_client):
        ai_chat.ask_about_repo(_analysis(), history=[], message=huge_message)

    _, kwargs = fake_client.models.generate_content.call_args
    last_message_text = kwargs['contents'][-1].parts[0].text
    assert len(last_message_text) < 5000 + 100


def test_ask_about_repo_handles_empty_message_without_calling_the_api():
    fake_client = MagicMock()

    with patch.object(ai_chat, '_client', return_value=fake_client):
        reply = ai_chat.ask_about_repo(_analysis(), history=[], message='   ')

    fake_client.models.generate_content.assert_not_called()
    assert reply


@pytest.mark.parametrize('exception', [
    genai_errors.ClientError(429, {'error': {'message': 'quota exceeded'}}),
    ConnectionError('network is down'),
    TimeoutError('timed out'),
])
def test_ask_about_repo_returns_fallback_on_api_failure(exception):
    fake_client = MagicMock()
    fake_client.models.generate_content.side_effect = exception

    with patch.object(ai_chat, '_client', return_value=fake_client):
        reply = ai_chat.ask_about_repo(_analysis(), history=[], message='hello')

    assert reply == ai_chat._FALLBACK_REPLY


def test_ask_about_repo_never_calls_the_real_network(monkeypatch):
    """Guard against accidentally hitting the real Gemini API in CI: with no
    key set and _client left un-mocked, constructing the real client (which
    ask_about_repo would do if the patch above weren't in place) raises
    before any network call - this test documents that expectation."""
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    with pytest.raises(KeyError):
        ai_chat._client()
