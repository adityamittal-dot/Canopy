import os

from parsing.extract import extract_symbols
from parsing.parse import parse_file

FIXTURE = os.path.join(os.path.dirname(__file__), 'fixtures', 'edge_cases.py')


def test_decorators_dont_hide_the_decorated_function():
    names = {s.name for s in extract_symbols(parse_file(FIXTURE), FIXTURE, 'edge')}

    assert 'edge.Widget.__init__' in names
    assert 'edge.decorator.wrapper' in names


def test_dunder_methods_are_captured_like_any_other_method():
    names = {s.name for s in extract_symbols(parse_file(FIXTURE), FIXTURE, 'edge')}

    assert {'edge.Widget.__init__', 'edge.Widget.__str__'} <= names


def test_async_methods_are_captured():
    by_name = {s.name: s for s in extract_symbols(parse_file(FIXTURE), FIXTURE, 'edge')}

    assert by_name['edge.Widget.refresh'].kind == 'function'


def test_lambdas_and_comprehensions_produce_no_symbols():
    names = {s.name for s in extract_symbols(parse_file(FIXTURE), FIXTURE, 'edge')}

    assert names == {
        'edge',
        'edge.decorator',
        'edge.decorator.wrapper',
        'edge.Widget',
        'edge.Widget.__init__',
        'edge.Widget.__str__',
        'edge.Widget.refresh',
    }
