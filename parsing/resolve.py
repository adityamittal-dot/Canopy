from dataclasses import dataclass

from parsing.extract import Symbol


@dataclass
class Edge:
    caller: str
    callee: str | None
    resolved: bool


def _bare_name(qualified_or_call: str) -> str:
    return qualified_or_call.rsplit('.', 1)[-1]


def resolve_calls(table: dict[str, Symbol]) -> list[Edge]:
    """Resolve every function's raw calls into call-graph edges.

    Same-file candidates are tried before repo-wide ones. A call that matches
    no known function becomes an unresolved edge (callee=None) rather than
    being dropped or guessed at.
    """
    functions = [s for s in table.values() if s.kind == 'function']
    by_bare_name: dict[str, list[Symbol]] = {}
    for func in functions:
        by_bare_name.setdefault(_bare_name(func.name), []).append(func)

    edges = []
    for caller in functions:
        for call in caller.calls:
            candidates = by_bare_name.get(_bare_name(call), [])
            same_file = [c for c in candidates if c.file == caller.file]
            match = same_file[0] if same_file else (candidates[0] if candidates else None)
            edges.append(
                Edge(caller=caller.name, callee=match.name if match else None, resolved=match is not None)
            )

    return edges
