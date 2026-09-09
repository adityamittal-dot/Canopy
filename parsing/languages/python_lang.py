"""Adapter wrapping the original ast-based Python pipeline behind the
LanguageAnalyzer interface, unchanged - Python's own extraction stays exactly
as precise/fast/dependency-free as it was before multi-language support."""

from parsing.extract import extract_symbols
from parsing.imports import extract_imports
from parsing.parse import parse_file


class PythonAnalyzer:
    extensions = frozenset({'.py'})
    language_id = 'python'

    def parse(self, path: str):
        return parse_file(path)

    def extract_symbols(self, tree, file: str, module_name: str):
        return extract_symbols(tree, file, module_name)

    def extract_imports(self, tree):
        return extract_imports(tree)


PYTHON_ANALYZER = PythonAnalyzer()
