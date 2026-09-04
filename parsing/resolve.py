from dataclasses import dataclass

from parsing.extract import Symbol


@dataclass
class Edge:
    caller: str
    callee: str | None
    resolved: bool


def bare_name(qualified_or_call: str) -> str:
    return qualified_or_call.rsplit('.', 1)[-1]


def _looks_local(call: str) -> bool:
    """True for calls that plausibly target a function/method in this repo,
    rather than an attribute chain into an imported module or object
    (e.g. `os.path.join`, `some_dict.get`) that only coincidentally shares
    a bare name with something defined here."""
    return '.' not in call or call.startswith(('self.', 'cls.'))


def resolve_calls(table: dict[str, Symbol]) -> list[Edge]:
    """Resolve every function's raw calls into call-graph edges.

    Same-file candidates are always tried first. Repo-wide (cross-file)
    fallback is only attempted for calls that look local (see
    `_looks_local`) — otherwise a dotted call into an imported module just
    happens to share a bare name with an unrelated repo function and gets
    matched by pure coincidence. A call that still matches nothing becomes
    an unresolved edge (callee=None) rather than being dropped or guessed.
    """
    functions = [s for s in table.values() if s.kind == 'function']
    by_bare_name: dict[str, list[Symbol]] = {}
    for func in functions:
        by_bare_name.setdefault(bare_name(func.name), []).append(func)

    edges = []
    for caller in functions:
        for call in caller.calls:
            candidates = by_bare_name.get(bare_name(call), [])
            same_file = [c for c in candidates if c.file == caller.file]
            if same_file:
                match = same_file[0]
            elif _looks_local(call):
                match = candidates[0] if candidates else None
            else:
                match = None
            edges.append(
                Edge(caller=caller.name, callee=match.name if match else None, resolved=match is not None)
            )

    return edges
