import os

from parsing.extract import extract_symbols
from parsing.parse import parse_file

FIXTURE = os.path.join(os.path.dirname(__file__), 'fixtures', 'nested_symbols.py')


def test_extract_symbols_captures_nesting():
    symbols = extract_symbols(parse_file(FIXTURE), file=FIXTURE, module_name='mod')

    assert {s.name for s in symbols} == {
        'mod',
        'mod.Outer',
        'mod.Outer.Inner',
        'mod.Outer.Inner.method',
        'mod.Outer.outer_method',
        'mod.Outer.outer_method.inner_function',
        'mod.fetch',
        'mod.top_level',
    }


def test_extract_symbols_records_kinds():
    by_name = {s.name: s for s in extract_symbols(parse_file(FIXTURE), FIXTURE, 'mod')}

    assert by_name['mod'].kind == 'module'
    assert by_name['mod.Outer'].kind == 'class'
    assert by_name['mod.fetch'].kind == 'function'


DOCUMENTED = os.path.join(os.path.dirname(__file__), 'fixtures', 'documented.py')


def test_extract_symbols_captures_docstrings():
    by_name = {s.name: s for s in extract_symbols(parse_file(DOCUMENTED), DOCUMENTED, 'doc')}

    assert by_name['doc'].docstring == 'Module docstring.'
    assert by_name['doc.Documented'].docstring == 'Class docstring.'
    assert by_name['doc.Documented.method'].docstring == 'Method docstring.'
    assert by_name['doc.undocumented'].docstring is None


def test_extract_symbols_records_line_ranges():
    by_name = {s.name: s for s in extract_symbols(parse_file(FIXTURE), FIXTURE, 'mod')}

    top_level = by_name['mod.top_level']
    assert (top_level.lineno, top_level.end_lineno) == (17, 18)
