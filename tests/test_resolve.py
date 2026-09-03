import os

from parsing.extract import extract_symbols
from parsing.parse import parse_file
from parsing.resolve import resolve_calls
from parsing.symbol_table import build_symbol_table

FIXTURE = os.path.join(os.path.dirname(__file__), 'fixtures', 'calls_sample.py')


def _edges():
    table = build_symbol_table(extract_symbols(parse_file(FIXTURE), FIXTURE, 'mod'))
    return resolve_calls(table)


def test_same_file_call_resolves():
    edges = _edges()

    assert any(e.caller == 'mod.Service.run' and e.callee == 'mod.helper' and e.resolved for e in edges)


def test_unresolvable_calls_are_kept_as_unresolved_not_dropped():
    edges = _edges()
    unresolved = [e for e in edges if e.caller == 'mod.Service.run' and not e.resolved]

    assert len(unresolved) == 3
    assert all(e.callee is None for e in unresolved)


def test_nested_functions_resolve_independently():
    edges = _edges()

    assert any(
        e.caller == 'mod.Service.run.nested' and e.callee == 'mod.helper' and e.resolved for e in edges
    )
