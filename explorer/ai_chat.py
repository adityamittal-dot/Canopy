"""Optional repo-scoped AI chat: answers questions about one already-analyzed
repo, grounded in Canopy's own parsed graph data rather than letting the
model free-associate. Entirely separate from (and never influences) the
deterministic parsing/graph pipeline - this module only exists to talk
*about* an already-computed CommitAnalysis.

Off by default: every function here is inert unless GEMINI_API_KEY is set
(see is_chat_enabled) - explorer/dash_apps.py doesn't even render the chat UI
when it's unset.
"""

import logging
import os
import re

from google.genai import errors as genai_errors

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = 'gemini-3.5-flash-lite'
_REQUEST_TIMEOUT_MS = 15_000
_MAX_HISTORY_TURNS = 6
_MAX_MESSAGE_CHARS = 1000
_MAX_CONTEXT_SYMBOLS = 8

_SYSTEM_INSTRUCTION = (
    "You are Canopy's repo assistant. Canopy statically parses a GitHub "
    "repository into a structural graph (modules, classes, functions, call "
    "edges) - you are answering questions about ONE specific repository "
    "using only the CONTEXT block the user provides, which was extracted "
    "from that repository's parsed graph. If the answer isn't in the "
    "context, say you don't know rather than guessing - never invent "
    "function names, file paths, or behavior that isn't in the context."
)

_FALLBACK_REPLY = 'AI chat is temporarily unavailable - try again in a moment.'

# Matched against the user's message via simple keyword overlap (not
# embeddings) to pick which of the repo's already-parsed symbols to include
# as context - deterministic, no extra infra, and the repo's own graph is
# already the source of truth.
_WORD_RE = re.compile(r'[a-zA-Z_][a-zA-Z0-9_]{2,}')


def is_chat_enabled() -> bool:
    return bool(os.environ.get('GEMINI_API_KEY'))


def _model_name() -> str:
    return os.environ.get('GEMINI_MODEL', _DEFAULT_MODEL)


def _client():
    from google import genai
    from google.genai import types

    return genai.Client(
        api_key=os.environ['GEMINI_API_KEY'],
        http_options=types.HttpOptions(timeout=_REQUEST_TIMEOUT_MS),
    )


def _matching_symbols(nodes: list[dict], message: str, limit: int = _MAX_CONTEXT_SYMBOLS) -> list[dict]:
    terms = {t.lower() for t in _WORD_RE.findall(message)}
    if not terms:
        return []

    scored = []
    for node in nodes:
        if node.get('kind') not in ('module', 'class', 'function'):
            continue
        haystack = f"{node.get('name', '')} {node.get('docstring') or ''}".lower()
        score = sum(1 for term in terms if term in haystack)
        if score:
            scored.append((score, node))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [node for _, node in scored[:limit]]


def build_repo_context(analysis, message: str) -> str:
    """A bounded context block - repo identity, top-level structure, and the
    symbols most relevant to `message` - so token usage never scales with
    repo size, however large the analyzed repo is."""
    graph = analysis.graph
    nodes = graph.get('nodes', [])

    lines = [
        f'Repository: {analysis.repo.name} ({analysis.repo.url})',
        f'Commit: {analysis.commit_hash}',
        f"{len(nodes)} symbols parsed across {len(graph.get('imports', {}))} files.",
    ]

    top_level = sorted({n['name'].split('.')[0] for n in nodes if n.get('kind') == 'module'})
    if top_level:
        lines.append('Top-level modules/packages: ' + ', '.join(top_level[:30]))

    matches = _matching_symbols(nodes, message)
    if matches:
        lines.append('')
        lines.append('Relevant symbols:')
        for node in matches:
            doc = f" - {node['docstring']}" if node.get('docstring') else ''
            location = f"{node.get('relative_path', '?')}:{node.get('lineno', '?')}"
            lines.append(f"- {node['kind']} `{node['name']}` ({location}){doc}")

    return '\n'.join(lines)


def ask_about_repo(analysis, history: list[dict], message: str) -> str:
    """history: [{'role': 'user'|'model', 'text': str}, ...], oldest first.
    Returns the assistant's reply text, or a friendly fallback string on any
    API/network failure - never raises into the calling Dash callback."""
    from google.genai import types

    message = message.strip()[:_MAX_MESSAGE_CHARS]
    if not message:
        return 'Ask me something about this repo.'

    context = build_repo_context(analysis, message)
    trimmed_history = history[-_MAX_HISTORY_TURNS:]

    contents = [
        types.Content(role=turn['role'], parts=[types.Part(text=turn['text'])])
        for turn in trimmed_history
    ]
    contents.append(types.Content(
        role='user',
        parts=[types.Part(text=f'CONTEXT:\n{context}\n\nQUESTION:\n{message}')],
    ))

    try:
        # Held in a local, not chained straight off _client() - the SDK's
        # Client owns the underlying httpx client and closes it when
        # garbage-collected, which (confirmed live) can happen mid-request
        # if nothing keeps the Client itself alive for the call's duration.
        client = _client()
        response = client.models.generate_content(
            model=_model_name(),
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_INSTRUCTION,
                max_output_tokens=800,
                temperature=0.2,
            ),
        )
    except (genai_errors.APIError, ConnectionError, TimeoutError):
        # Logged (not just swallowed) so a real failure - bad key, wrong
        # model id, quota exceeded, network issue - shows up in the
        # deployment's logs instead of only ever surfacing as the generic
        # fallback string below with no way to tell which cause it was.
        logger.exception('Gemini chat request failed; returning fallback reply')
        return _FALLBACK_REPLY

    return (response.text or '').strip() or "I couldn't come up with an answer to that."
