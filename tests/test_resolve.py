import os

from parsing.extract import Symbol, extract_symbols
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


def test_same_bare_name_in_different_language_does_not_cross_resolve():
    """In a polyglot repo, a JS `run()` and a Python `run()` sharing a bare
    name are never actually the same call target - resolve_calls must not
    match across languages just because the names collide."""
    dispatcher = Symbol(kind='function', name='py_mod.dispatch', file='py_mod.py', calls=['run'], language='python')
    js_run = Symbol(kind='function', name='js_mod.run', file='js_mod.js', calls=[], language='javascript')
    table = build_symbol_table([dispatcher, js_run])

    edges = resolve_calls(table)

    edge = next(e for e in edges if e.caller == 'py_mod.dispatch')
    assert edge.resolved is False
    assert edge.callee is None


def test_same_bare_name_in_same_language_still_resolves_cross_file():
    dispatcher = Symbol(kind='function', name='mod_a.dispatch', file='mod_a.py', calls=['run'], language='python')
    py_run = Symbol(kind='function', name='mod_b.run', file='mod_b.py', calls=[], language='python')
    table = build_symbol_table([dispatcher, py_run])

    edges = resolve_calls(table)

    edge = next(e for e in edges if e.caller == 'mod_a.dispatch')
    assert edge.resolved is True
    assert edge.callee == 'mod_b.run'
