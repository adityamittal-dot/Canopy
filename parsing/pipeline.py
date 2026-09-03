import dataclasses
import os

from parsing.clone import clone_repo
from parsing.extract import Symbol, extract_symbols
from parsing.imports import extract_imports
from parsing.metrics import compute_fan_in_out, compute_loc
from parsing.parse import parse_files
from parsing.resolve import resolve_calls
from parsing.symbol_table import build_symbol_table
from parsing.walk import find_python_files


def _module_name(file: str, repo_root: str) -> str:
    rel = os.path.relpath(file, repo_root).removesuffix('.py')
    return rel.replace(os.sep, '.')


def _node_dict(symbol: Symbol, fan: dict[str, tuple[int, int]]) -> dict:
    node = dataclasses.asdict(symbol)
    node['loc'] = compute_loc(symbol)
    node['fan_in'], node['fan_out'] = fan.get(symbol.name, (0, 0))
    return node


def analyze_repo(url: str) -> dict:
    """Run the full parsing pipeline against a repo URL: clone, parse, extract, resolve, measure."""
    repo_root, commit_hash = clone_repo(url)
    trees, parse_failures = parse_files(find_python_files(repo_root))

    symbols = []
    imports: dict[str, list[str]] = {}
    for file, tree in trees.items():
        symbols += extract_symbols(tree, file, _module_name(file, repo_root))
        imports[file] = extract_imports(tree)

    edges = resolve_calls(build_symbol_table(symbols))
    fan = compute_fan_in_out(edges)

    return {
        'commit_hash': commit_hash,
        'parse_failures': [{'file': f, 'error': str(e)} for f, e in parse_failures],
        'nodes': [_node_dict(s, fan) for s in symbols],
        'edges': [dataclasses.asdict(e) for e in edges],
        'imports': imports,
    }
