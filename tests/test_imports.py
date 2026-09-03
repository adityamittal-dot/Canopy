import os

from parsing.imports import extract_imports
from parsing.parse import parse_file

FIXTURE = os.path.join(os.path.dirname(__file__), 'fixtures', 'imports_sample.py')


def test_extract_imports():
    imports = extract_imports(parse_file(FIXTURE))

    assert imports == [
        'os',
        'os.path',
        'collections.OrderedDict',
        '.sibling',
        '.pkg.helper',
        '..pkg.other',
    ]
