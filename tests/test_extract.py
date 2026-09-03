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
