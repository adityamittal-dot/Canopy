"""End-to-end pipeline test against a small synthetic polyglot repo (a real
local directory, not a clone - see parsing.pipeline.analyze_local_repo) to
prove the multi-language dispatch, cross-language-safe call resolution, and
explorer.graph_data rendering all work together, not just in isolation."""

import os
import shutil
import tempfile

import pytest

from explorer.graph_data import build_elements
from parsing.pipeline import analyze_local_repo

PY_SOURCE = '''
def helper():
    return 1


def run():
    return helper()
'''

JS_SOURCE = '''
function helper() {
  return 2;
}

function run() {
  return helper();
}
'''

GO_SOURCE = '''
package main

func Helper() int {
	return 3
}

func Run() int {
	return Helper()
}
'''


@pytest.fixture
def polyglot_repo():
    root = tempfile.mkdtemp()
    os.makedirs(os.path.join(root, 'pkg'), exist_ok=True)
    with open(os.path.join(root, 'main.py'), 'w') as f:
        f.write(PY_SOURCE)
    with open(os.path.join(root, 'pkg', 'app.js'), 'w') as f:
        f.write(JS_SOURCE)
    with open(os.path.join(root, 'pkg', 'server.go'), 'w') as f:
        f.write(GO_SOURCE)
    with open(os.path.join(root, 'README.md'), 'w') as f:
        f.write('# not a source file, should be silently skipped\n')
    yield root
    shutil.rmtree(root, ignore_errors=True)


def test_analyze_local_repo_covers_every_language(polyglot_repo):
    result = analyze_local_repo(polyglot_repo, commit_hash='f' * 40)

    assert result['parse_failures'] == []
    languages = {n['language'] for n in result['nodes']}
    assert languages == {'python', 'javascript', 'go'}


def test_analyze_local_repo_resolves_calls_within_each_language(polyglot_repo):
    result = analyze_local_repo(polyglot_repo, commit_hash='f' * 40)

    by_language = {}
    for edge in result['edges']:
        caller_node = next(n for n in result['nodes'] if n['name'] == edge['caller'])
        by_language.setdefault(caller_node['language'], []).append(edge)

    for language, edges in by_language.items():
        run_edges = [e for e in edges if e['caller'].endswith('.run') or e['caller'].endswith('.Run')]
        assert run_edges, f'no run() edge found for {language}'
        assert all(e['resolved'] for e in run_edges), f'{language} run() call did not resolve'


def test_analyze_local_repo_does_not_cross_resolve_same_named_functions_across_languages(polyglot_repo):
    result = analyze_local_repo(polyglot_repo, commit_hash='f' * 40)

    for edge in result['edges']:
        if not edge['resolved']:
            continue
        caller_node = next(n for n in result['nodes'] if n['name'] == edge['caller'])
        callee_node = next(n for n in result['nodes'] if n['name'] == edge['callee'])
        assert caller_node['language'] == callee_node['language'], (
            f"cross-language false-positive edge: {edge['caller']} ({caller_node['language']}) "
            f"-> {edge['callee']} ({callee_node['language']})"
        )


def test_graph_data_renders_the_polyglot_result_without_error(polyglot_repo):
    result = analyze_local_repo(polyglot_repo, commit_hash='f' * 40)

    elements = build_elements(result, repo_label='polyglot-repo')

    kinds = {el['data']['kind'] for el in elements}
    assert 'call' in kinds
    assert 'function' in kinds
    # three languages -> at least three distinct module nodes
    module_labels = {el['data']['label'] for el in elements if el['data']['kind'] == 'module'}
    assert len(module_labels) >= 3
