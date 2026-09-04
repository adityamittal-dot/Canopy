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
            'name': name,
            'relative_path': node.get('relative_path'),
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


def subtree_node_count(elements: list[dict], root_id: str) -> int:
    """Count module/class/function nodes in the subtree rooted at `root_id`
    (including `root_id` itself if it's one of those kinds). Packages don't
    count on their own - they're just containers - so this reflects how
    many real symbols a filtered-out branch is actually hiding."""
    by_id = {el['data']['id']: el for el in elements if el['data'].get('kind') != 'call'}
    children_index = index_children(elements)

    count = 0
    stack = [root_id]
    while stack:
        node_id = stack.pop()
        node = by_id.get(node_id)
        if node is None:
            continue
        if node['data']['kind'] in ('module', 'class', 'function'):
            count += 1
        stack.extend(child['data']['id'] for child in children_index.get(node_id, []))
    return count


def ancestors_of(elements: list[dict], node_id: str) -> list[str]:
    """Ids of `node_id`'s ancestors, immediate parent first, up to (but not
    including) the repo root. Used to reveal a node that isn't currently
    visible - expanding every id this returns makes `node_id` visible."""
    parent_by_id = {el['data']['id']: el['data'].get('parent') for el in elements if el['data'].get('kind') != 'call'}

    ancestors = []
    parent_id = parent_by_id.get(node_id)
    while parent_id is not None and parent_id != 'repo':
        ancestors.append(parent_id)
        parent_id = parent_by_id.get(parent_id)
    return ancestors


def callers_and_callees(elements: list[dict], node_id: str) -> tuple[list[str], list[str]]:
    """Ids of every node with a resolved call edge into/out of `node_id`."""
    callers = []
    callees = []
    for el in elements:
        data = el['data']
        if data.get('kind') != 'call':
            continue
        if data['target'] == node_id:
            callers.append(data['source'])
        if data['source'] == node_id:
            callees.append(data['target'])
    return callers, callees


# parsing.walk already excludes .git/venv/node_modules/__pycache__ at parse
# time (they're never even walked), so those never reach here at all. What's
# left as separately-filterable categories for display purposes are test code
# and vendored/third-party dependencies - both still parsed and present in
# the data, just hidden by default in the graph view (two independent
# toggles - see explorer/dash_apps.py).
_TEST_PACKAGE_NAMES = {'test', 'tests', 'testing'}
_VENDOR_PACKAGE_NAMES = {'vendor', 'vendored', 'third_party', 'thirdparty', 'site-packages', 'dist-packages', '.eggs'}


def _is_test_module_filename(relative_path: str) -> bool:
    filename = relative_path.rsplit('/', 1)[-1]
    stem = filename.removesuffix('.py')
    return stem.startswith('test_') or stem.endswith(('_test', '_tests'))


def _category_ids(elements: list[dict], is_own_category) -> set[str]:
    """Shared propagation logic for one filter category: a node is in the
    category if it matches directly, or its parent is already in it.
    Relies on the same parent-before-child ordering invariant as
    build_elements (see module docstring) - a single left-to-right pass is
    enough to propagate a matching ancestor's status down to every
    descendant."""
    marked: set[str] = set()
    for el in elements:
        data = el['data']
        if data.get('kind') == 'call':
            continue
        if is_own_category(data) or data.get('parent') in marked:
            marked.add(data['id'])
    return marked


def noise_ids_for_tests(elements: list[dict]) -> set[str]:
    """Ids of nodes that are test code - a test/tests/testing package, or a
    test_*.py/*_test.py/*_tests.py module - or descend from one."""
    def is_own(data: dict) -> bool:
        if data['kind'] == 'package':
            return data['label'].lower() in _TEST_PACKAGE_NAMES
        if data['kind'] == 'module':
            return bool(data.get('relative_path')) and _is_test_module_filename(data['relative_path'])
        return False

    return _category_ids(elements, is_own)


def vendor_noise_ids(elements: list[dict]) -> set[str]:
    """Ids of nodes that are vendored/third-party dependency code - a
    vendor/third_party/site-packages-style package - or descend from one."""
    def is_own(data: dict) -> bool:
        return data['kind'] == 'package' and data['label'].lower() in _VENDOR_PACKAGE_NAMES

    return _category_ids(elements, is_own)
