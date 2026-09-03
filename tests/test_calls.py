import os

from parsing.extract import extract_symbols
from parsing.parse import parse_file

FIXTURE = os.path.join(os.path.dirname(__file__), 'fixtures', 'calls_sample.py')


def test_extract_calls_finds_direct_calls_including_attribute_chains():
    by_name = {s.name: s for s in extract_symbols(parse_file(FIXTURE), FIXTURE, 'mod')}

    assert by_name['mod.Service.run'].calls == [
        'helper',
        'self.prepare',
        'os.path.join',
        'self.log.warning',
    ]


def test_extract_calls_does_not_descend_into_nested_functions():
    by_name = {s.name: s for s in extract_symbols(parse_file(FIXTURE), FIXTURE, 'mod')}

    assert by_name['mod.Service.run.nested'].calls == ['helper']
    assert by_name['mod.Service.run'].calls.count('helper') == 1


def test_non_function_symbols_have_no_calls():
    by_name = {s.name: s for s in extract_symbols(parse_file(FIXTURE), FIXTURE, 'mod')}

    assert by_name['mod'].calls == []
    assert by_name['mod.Service'].calls == []
