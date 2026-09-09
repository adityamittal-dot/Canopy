"""Parametrized coverage for every non-Python LanguageAnalyzer registered in
parsing.languages. One shared fixture shape per language (tests/fixtures/
multilang/sample.<ext>): a documented top-level `add` function with a branch
and a call, and a `Widget` class/struct with a documented `render`-ish method
that calls `add` both via a receiver and bare. Mirrors what tests/test_extract.py
already checks for the ast-based Python path - kind, nesting, docstring,
calls, complexity - just parametrized across languages instead of one file
per assertion set, since the shape of what's being verified is identical.
"""

import os

import pytest

from parsing.languages import LANGUAGE_REGISTRY

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures', 'multilang')

# (extension, add's qualified name, add's docstring, add's calls, add's complexity,
#  class-or-struct qualified name, method qualified name, method's docstring, method's calls)
CASES = [
    ('.js', 'sample.add', 'Adds two numbers.', ['helper.scale'], 2,
     'sample.Widget', 'sample.Widget.render', 'Renders the widget.', ['this.add', 'add']),
    ('.ts', 'sample.add', 'Adds two numbers.', ['helper.scale'], 2,
     'sample.Widget', 'sample.Widget.render', 'Renders the widget.', ['this.add', 'add']),
    ('.go', 'sample.Add', 'Add adds two ints.', ['helper.Scale'], 2,
     'sample.Widget', 'sample.Widget.Render', 'Render renders w.', ['w.Add']),
    ('.java', 'sample.Widget.add', 'Adds two ints.', ['helper.scale'], 2,
     'sample.Widget', 'sample.Widget.render', 'Renders the widget.', ['this.add']),
    ('.rs', 'sample.add', 'Adds two numbers.', ['helper.scale'], 2,
     'sample.Widget', 'sample.Widget.render', 'Renders the widget.', ['self.add']),
    ('.c', 'sample.add', 'Adds two ints.', ['helper_scale'], 2,
     None, None, None, None),
    ('.cpp', 'sample.Widget.add', 'Adds two ints.', ['helper.scale'], 2,
     'sample.Widget', 'sample.Widget.render', 'Renders the widget.', ['this.add']),
    ('.rb', 'sample.add', 'Adds two numbers.', ['helper.scale'], 2,
     'sample.Widget', 'sample.Widget.render', 'Renders the widget.', ['add']),
    ('.php', 'sample.add', 'Adds two ints.', ['helper.scale'], 2,
     'sample.Widget', 'sample.Widget.render', 'Renders the widget.', ['this.add', 'add']),
    ('.cs', 'sample.Widget.Add', 'Adds two ints.', ['Helper.Scale'], 2,
     'sample.Widget', 'sample.Widget.Render', 'Renders the widget.', ['this.Add']),
]

FIXTURE_BASENAME = {
    '.js': 'sample.js', '.ts': 'sample.ts', '.go': 'sample.go', '.java': 'Sample.java',
    '.rs': 'sample.rs', '.c': 'sample.c', '.cpp': 'sample.cpp', '.rb': 'sample.rb',
    '.php': 'sample.php', '.cs': 'Sample.cs',
}


def _extract(ext):
    path = os.path.join(FIXTURES_DIR, FIXTURE_BASENAME[ext])
    analyzer = LANGUAGE_REGISTRY[ext]
    tree = analyzer.parse(path)
    symbols = analyzer.extract_symbols(tree, path, 'sample')
    return {s.name: s for s in symbols}


@pytest.mark.parametrize(
    'ext,add_name,add_doc,add_calls,add_complexity,cls_name,method_name,method_doc,method_calls',
    CASES,
)
def test_language_extracts_function_and_class(
    ext, add_name, add_doc, add_calls, add_complexity, cls_name, method_name, method_doc, method_calls,
):
    by_name = _extract(ext)

    assert add_name in by_name
    add = by_name[add_name]
    assert add.kind == 'function'
    assert add.docstring == add_doc
    assert add.calls == add_calls
    assert add.complexity == add_complexity
    assert add.lineno >= 1
    assert add.end_lineno >= add.lineno

    if cls_name is not None:
        assert by_name[cls_name].kind == 'class'
        method = by_name[method_name]
        assert method.kind == 'function'
        assert method.docstring == method_doc
        assert method.calls == method_calls


@pytest.mark.parametrize('ext', [c[0] for c in CASES])
def test_language_id_matches_registry(ext):
    analyzer = LANGUAGE_REGISTRY[ext]
    by_name = _extract(ext)
    assert all(s.language == analyzer.language_id for s in by_name.values())


@pytest.mark.parametrize('ext', [c[0] for c in CASES])
def test_module_symbol_always_present(ext):
    by_name = _extract(ext)
    assert 'sample' in by_name
    assert by_name['sample'].kind == 'module'
