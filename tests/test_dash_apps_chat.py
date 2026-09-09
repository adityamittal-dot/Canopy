"""explorer.dash_apps decides whether to build the chat UI at all once, at
module-import time, based on whether GEMINI_API_KEY is set (see
explorer/ai_chat.py's is_chat_enabled and dash_apps.py's _CHAT_ENABLED) - so
testing "present when enabled" means importing the module fresh with the
env var set. Doing that via subprocess rather than importlib.reload avoids
re-registering the module-level DjangoDash('RepoGraph', ...) singleton
against django-plotly-dash's app registry a second time in the same process,
which raises a duplicate-app error.
"""

import subprocess
import sys

_PROBE = '''
import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "canopy.settings")
django.setup()

from explorer import dash_apps

assert dash_apps._CHAT_ENABLED is {expected}, "unexpected _CHAT_ENABLED"

layout_ids = set()
def collect(node):
    node_id = getattr(node, "id", None)
    if node_id:
        layout_ids.add(node_id)
    for child in getattr(node, "children", None) or []:
        if not isinstance(child, str):
            collect(child)

collect(dash_apps.graph_app.layout)

chat_ids = {{"toggle-chat", "cy-chat", "chat-input", "chat-send", "chat-close"}}
present = chat_ids & layout_ids
expected_present = chat_ids if {expected} else set()
assert present == expected_present, f"chat ids present={{present}}, expected={{expected_present}}"

print("OK")
'''


def _run_probe(expected: bool, gemini_key: str | None) -> subprocess.CompletedProcess:
    import os
    env = os.environ.copy()
    env['DJANGO_DEBUG'] = 'True'
    if gemini_key is None:
        env.pop('GEMINI_API_KEY', None)
    else:
        env['GEMINI_API_KEY'] = gemini_key

    script = _PROBE.format(expected=expected)
    return subprocess.run(
        [sys.executable, '-c', script],
        capture_output=True, text=True, env=env, timeout=60,
    )


def test_chat_ui_absent_when_gemini_api_key_unset():
    result = _run_probe(expected=False, gemini_key=None)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'OK' in result.stdout


def test_chat_ui_present_when_gemini_api_key_set():
    result = _run_probe(expected=True, gemini_key='fake-key-for-testing')
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'OK' in result.stdout
