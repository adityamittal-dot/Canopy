"""The interface every per-language analyzer implements, plus the extension
-> analyzer registry that `parsing.walk`/`parsing.pipeline` dispatch through.

Keeping this interface tiny (parse + extract_symbols + extract_imports) is
what makes adding a language additive rather than a rewrite: everything
downstream of these three calls (parsing.resolve, parsing.metrics,
parsing.symbol_table, explorer.graph_data) already operates on the generic
Symbol/Edge dataclasses and has no language-specific logic at all.
"""

import os
from typing import Any, Protocol


class LanguageAnalyzer(Protocol):
    extensions: frozenset[str]
    language_id: str

    def parse(self, path: str) -> Any:
        """Read and parse `path`. Raises parsing.parse.ParseError on failure."""
        ...

    def extract_symbols(self, tree: Any, file: str, module_name: str) -> list:
        ...

    def extract_imports(self, tree: Any) -> list[str]:
        ...


LANGUAGE_REGISTRY: dict[str, LanguageAnalyzer] = {}


def register(analyzer: LanguageAnalyzer) -> LanguageAnalyzer:
    for ext in analyzer.extensions:
        LANGUAGE_REGISTRY[ext] = analyzer
    return analyzer


def analyzer_for(path: str) -> LanguageAnalyzer | None:
    """The registered analyzer for `path`'s extension, or None if unrecognized
    (an unrecognized extension is never an error - see parsing.walk/pipeline -
    it just means that file doesn't contribute nodes to the graph)."""
    ext = os.path.splitext(path)[1]
    return LANGUAGE_REGISTRY.get(ext)
