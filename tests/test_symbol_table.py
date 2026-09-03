import os

from parsing.extract import extract_symbols
from parsing.parse import parse_file
from parsing.symbol_table import build_symbol_table

FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures')


def test_build_symbol_table_spans_multiple_files():
    file_a = os.path.join(FIXTURES, 'nested_symbols.py')
    file_b = os.path.join(FIXTURES, 'calls_sample.py')

    symbols = extract_symbols(parse_file(file_a), file_a, 'pkg.a') + extract_symbols(
        parse_file(file_b), file_b, 'pkg.b'
    )
    table = build_symbol_table(symbols)

    assert 'pkg.a.top_level' in table
    assert 'pkg.b.Service.run' in table
    assert table['pkg.b.Service.run'].file == file_b
