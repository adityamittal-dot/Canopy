import os

from parsing.extract import extract_symbols
from parsing.metrics import compute_fan_in_out
from parsing.parse import parse_file
from parsing.resolve import resolve_calls
from parsing.symbol_table import build_symbol_table

FIXTURE = os.path.join(os.path.dirname(__file__), 'fixtures', 'calls_sample.py')


def test_fan_in_and_fan_out():
    table = build_symbol_table(extract_symbols(parse_file(FIXTURE), FIXTURE, 'mod'))
    fan = compute_fan_in_out(resolve_calls(table))

    # helper() is called by both Service.run and Service.run.nested -> fan_in 2
    assert fan['mod.helper'] == (2, 0)

    # Service.run calls helper once (resolved) among its several calls -> fan_out 1
    assert fan['mod.Service.run'] == (0, 1)


def test_functions_with_no_resolved_edges_are_absent():
    table = build_symbol_table(extract_symbols(parse_file(FIXTURE), FIXTURE, 'mod'))
    fan = compute_fan_in_out(resolve_calls(table))

    assert 'mod.Service' not in fan
