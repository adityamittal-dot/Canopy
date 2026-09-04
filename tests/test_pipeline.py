import os

from parsing.extract import Symbol
from parsing.pipeline import _node_dict, analyze_repo


def test_analyze_repo_end_to_end():
    result = analyze_repo('https://github.com/pypa/sampleproject')

    assert len(result['commit_hash']) == 40
    assert result['parse_failures'] == []
    assert len(result['nodes']) > 0
    assert all(n['kind'] in ('module', 'class', 'function') for n in result['nodes'])
    assert all('resolved' in e for e in result['edges'])
    assert len(result['imports']) > 0
    assert all('relative_path' in n for n in result['nodes'])


def test_node_dict_relative_path_is_forward_slashed():
    # Built with os.path.join so this exercises the real local path
    # separator (backslash on Windows) - relative_path must still come out
    # forward-slashed, since it's meant for building GitHub URLs, not local
    # filesystem access.
    repo_root = os.path.join('tmp', 'clone123')
    file = os.path.join(repo_root, 'pkg', 'sub', 'mod.py')
    symbol = Symbol(kind='module', name='pkg.sub.mod', file=file)

    node = _node_dict(symbol, {}, repo_root)

    assert node['relative_path'] == 'pkg/sub/mod.py'
    assert '\\' not in node['relative_path']


def test_node_dict_relative_path_for_dunder_init():
    repo_root = os.path.join('tmp', 'clone123')
    file = os.path.join(repo_root, 'pkg', '__init__.py')
    symbol = Symbol(kind='module', name='pkg.__init__', file=file)

    node = _node_dict(symbol, {}, repo_root)

    assert node['relative_path'] == 'pkg/__init__.py'


def test_node_dict_relative_path_for_top_level_module():
    repo_root = os.path.join('tmp', 'clone123')
    file = os.path.join(repo_root, 'main.py')
    symbol = Symbol(kind='module', name='main', file=file)

    node = _node_dict(symbol, {}, repo_root)

    assert node['relative_path'] == 'main.py'
