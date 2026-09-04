"""Transforms parsing.pipeline.analyze_repo's flat nodes/edges into a
Cytoscape element list with a repo -> packages -> modules -> classes ->
functions containment hierarchy (compound nodes), plus call edges between
resolved function calls.

Relies on an invariant of parsing.extract.SymbolVisitor: within a single
file's symbol list, a symbol's enclosing scope (module, class, or function)
is always recorded before the symbol itself, and parsing.pipeline.analyze_repo
concatenates each file's symbols in that same order without interleaving
files. So a single left-to-right pass over `graph['nodes']` guarantees every
class/function node's immediate parent (found by stripping the last dotted
segment off its qualified name) has already been assigned an element id by
the time that node is processed.
"""

from parsing.resolve import bare_name as _label


def build_elements(graph: dict, repo_label: str = 'repo') -> list[dict]:
    """Build a Cytoscape elements list (nodes + call edges) from a pipeline result.

    Every node's `data` carries `depth` (repo=0) and `parent` (omitted only
    for the repo root), so a caller can render progressively by filtering on
    depth and/or on which parents have been "expanded".

    Two symbols can share the same fully-qualified name (e.g. a @property
    getter/setter/deleter, all named Class.x) - parsing.extract doesn't
    merge these, so the id for the second (and any later) occurrence is
    disambiguated with a `#2`, `#3`, ... suffix rather than colliding with
    the first, which Cytoscape requires to have a unique id.
    """
    elements = [{'data': {'id': 'repo', 'label': repo_label, 'kind': 'repo', 'depth': 0}}]
    depth_by_id = {'repo': 0}
    package_id_by_prefix: dict[str, str] = {}
    id_by_symbol_name: dict[str, str] = {}
    occurrences_by_id: dict[str, int] = {}

    def make_unique_id(candidate_id: str) -> str:
        count = occurrences_by_id.get(candidate_id, 0) + 1
        occurrences_by_id[candidate_id] = count
        return candidate_id if count == 1 else f'{candidate_id}#{count}'

    def ensure_package_chain(package_parts: list[str]) -> str:
        parent_id = 'repo'
        prefix_parts: list[str] = []
        for part in package_parts:
            prefix_parts.append(part)
            prefix_key = '.'.join(prefix_parts)
            pkg_id = package_id_by_prefix.get(prefix_key)
            if pkg_id is None:
                pkg_id = f'pkg:{prefix_key}'
                package_id_by_prefix[prefix_key] = pkg_id
                depth_by_id[pkg_id] = depth_by_id[parent_id] + 1
                elements.append({'data': {
                    'id': pkg_id,
                    'label': part,
                    'kind': 'package',
                    'parent': parent_id,
                    'depth': depth_by_id[pkg_id],
                }})
            parent_id = pkg_id
        return parent_id

    for node in graph.get('nodes', []):
        kind = node['kind']
        name = node['name']

        if kind == 'module':
            parts = name.split('.')
            parent_id = ensure_package_chain(parts[:-1])
            node_id = make_unique_id(f'mod:{name}')
        else:
            parent_name = name.rsplit('.', 1)[0]
            parent_id = id_by_symbol_name.get(parent_name)
            if parent_id is None:
                # A symbol's enclosing scope is always recorded first (see
                # module docstring) - this should be unreachable. Fail loudly
                # rather than silently attaching the node to the wrong parent.
                raise ValueError(f'no parent found for {kind} {name!r}')
            node_id = make_unique_id(f'sym:{name}')

        depth_by_id[node_id] = depth_by_id[parent_id] + 1
        id_by_symbol_name[name] = node_id

        elements.append({'data': {
            'id': node_id,
            'label': _label(name),
            'kind': kind,
            'parent': parent_id,
            'depth': depth_by_id[node_id],
            'file': node.get('file'),
            'docstring': node.get('docstring'),
            'lineno': node.get('lineno'),
            'end_lineno': node.get('end_lineno'),
            'complexity': node.get('complexity'),
            'loc': node.get('loc'),
            'fan_in': node.get('fan_in'),
            'fan_out': node.get('fan_out'),
        }})

    seen_call_edges: set[tuple[str, str]] = set()
    for edge in graph.get('edges', []):
        if not edge.get('resolved'):
            continue
        source_id = id_by_symbol_name.get(edge['caller'])
        target_id = id_by_symbol_name.get(edge['callee'])
        if source_id is None or target_id is None or (source_id, target_id) in seen_call_edges:
            continue
        seen_call_edges.add((source_id, target_id))
        elements.append({'data': {
            'id': f'call:{source_id}->{target_id}',
            'source': source_id,
            'target': target_id,
            'kind': 'call',
        }})

    return elements


def children_of(elements: list[dict], parent_id: str) -> list[dict]:
    """Direct child nodes of `parent_id` (edges have no parent, so never match)."""
    return [el for el in elements if el['data'].get('parent') == parent_id]


def index_children(elements: list[dict]) -> dict[str, list[dict]]:
    """Map parent id -> list of its direct child nodes, built in one pass.

    Use this instead of repeated `children_of` calls when checking children
    for more than one parent at a time (e.g. every currently-expanded node).
    """
    index: dict[str, list[dict]] = {}
    for el in elements:
        parent_id = el['data'].get('parent')
        if parent_id is not None:
            index.setdefault(parent_id, []).append(el)
    return index
