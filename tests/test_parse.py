import ast
import os

from parsing.parse import parse_file, parse_files

FIXTURE = os.path.join(os.path.dirname(__file__), 'fixtures', 'quirky_syntax.py')


def test_parse_file_handles_quirky_syntax():
    tree = parse_file(FIXTURE)

    assert isinstance(tree, ast.Module)


def test_parse_files_reports_no_failures_for_valid_file():
    trees, failures = parse_files([FIXTURE])

    assert FIXTURE in trees
    assert isinstance(trees[FIXTURE], ast.Module)
    assert failures == []
