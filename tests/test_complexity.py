import os

from parsing.extract import extract_symbols
from parsing.parse import parse_file

FIXTURE = os.path.join(os.path.dirname(__file__), 'fixtures', 'complexity_sample.py')


def test_simple_function_has_baseline_complexity():
    by_name = {s.name: s for s in extract_symbols(parse_file(FIXTURE), FIXTURE, 'mod')}

    assert by_name['mod.simple'].complexity == 1


def test_branches_and_boolean_operators_increase_complexity():
    by_name = {s.name: s for s in extract_symbols(parse_file(FIXTURE), FIXTURE, 'mod')}

    # baseline(1) + if + elif + for + while + except + if + (x and y) + (... or ...)
    assert by_name['mod.branchy'].complexity == 9
