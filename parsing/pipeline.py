import dataclasses
import os

from parsing.clone import clone_repo
from parsing.extract import Symbol
from parsing.languages import analyzer_for
from parsing.metrics import compute_fan_in_out, compute_loc
from parsing.parse import ParseError
from parsing.resolve import resolve_calls
from parsing.symbol_table import build_symbol_table
from parsing.walk import find_source_files


def _module_name(file: str, repo_root: str) -> str:
    rel, _ext = os.path.splitext(os.path.relpath(file, repo_root))
    return rel.replace(os.sep, '.')


def _node_dict(symbol: Symbol, fan: dict[str, tuple[int, int]], repo_root: str) -> dict:
    node = dataclasses.asdict(symbol)
    node['loc'] = compute_loc(symbol)
    node['fan_in'], node['fan_out'] = fan.get(symbol.name, (0, 0))
    # Forward-slashed regardless of OS, since this is meant for building
    # GitHub URLs (and other web-facing links), not local filesystem access.
    node['relative_path'] = os.path.relpath(symbol.file, repo_root).replace(os.sep, '/')
    return node


def analyze_repo(url: str) -> dict:
    """Run the full parsing pipeline against a repo URL: clone, then analyze_local_repo."""
    repo_root, commit_hash = clone_repo(url)
    return analyze_local_repo(repo_root, commit_hash)


def analyze_local_repo(repo_root: str, commit_hash: str) -> dict:
    """The parse/extract/resolve/measure pipeline against an already-present
    local directory - split out from analyze_repo so it's testable without a
    real clone (see tests/test_multilang_pipeline.py).

    Every source file is dispatched to the LanguageAnalyzer registered for
    its extension (parsing.languages.LANGUAGE_REGISTRY) - a file whose
    extension isn't registered was never even collected by find_source_files,
    so "any type of repo" degrades gracefully: non-code and unsupported-
    language files just contribute nothing, never an error.
    """
    symbols = []
    imports: dict[str, list[str]] = {}
    parse_failures: list[tuple[str, ParseError]] = []
    for file in find_source_files(repo_root):
        analyzer = analyzer_for(file)
        try:
            tree = analyzer.parse(file)
        except ParseError as exc:
            parse_failures.append((file, exc))
            continue
        symbols += analyzer.extract_symbols(tree, file, _module_name(file, repo_root))
        imports[file] = analyzer.extract_imports(tree)

    edges = resolve_calls(build_symbol_table(symbols))
    fan = compute_fan_in_out(edges)

    return {
        'commit_hash': commit_hash,
        'parse_failures': [{'file': f, 'error': str(e)} for f, e in parse_failures],
        'nodes': [_node_dict(s, fan, repo_root) for s in symbols],
        'edges': [dataclasses.asdict(e) for e in edges],
        'imports': imports,
    }
