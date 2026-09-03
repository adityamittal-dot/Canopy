import os

from parsing.extract import extract_symbols
from parsing.metrics import compute_loc
from parsing.parse import parse_file

FIXTURE = os.path.join(os.path.dirname(__file__), 'fixtures', 'nested_symbols.py')


def test_compute_loc():
    by_name = {s.name: s for s in extract_symbols(parse_file(FIXTURE), FIXTURE, 'mod')}

    assert compute_loc(by_name['mod.top_level']) == 2
    assert compute_loc(by_name['mod.Outer']) == 10


def test_compute_loc_for_module_symbol_is_zero():
    by_name = {s.name: s for s in extract_symbols(parse_file(FIXTURE), FIXTURE, 'mod')}

    assert compute_loc(by_name['mod']) == 0
