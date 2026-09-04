from explorer.graph_data import build_elements, children_of


def _by_id(elements, element_id):
    return next(el for el in elements if el['data']['id'] == element_id)


def _make_graph(nodes, edges=()):
    return {'nodes': nodes, 'edges': list(edges)}


def test_top_level_module_parents_directly_to_repo():
    graph = _make_graph([
        {'kind': 'module', 'name': 'main', 'file': 'main.py'},
    ])

    elements = build_elements(graph)

    module = _by_id(elements, 'mod:main')
    assert module['data']['parent'] == 'repo'
    assert module['data']['depth'] == 1
    assert module['data']['label'] == 'main'


def test_nested_module_synthesizes_package_chain():
    graph = _make_graph([
        {'kind': 'module', 'name': 'pkg.sub.mod', 'file': 'pkg/sub/mod.py'},
    ])

    elements = build_elements(graph)

    pkg = _by_id(elements, 'pkg:pkg')
    subpkg = _by_id(elements, 'pkg:pkg.sub')
    module = _by_id(elements, 'mod:pkg.sub.mod')

    assert pkg['data']['parent'] == 'repo'
    assert pkg['data']['depth'] == 1
    assert subpkg['data']['parent'] == 'pkg:pkg'
    assert subpkg['data']['depth'] == 2
    assert module['data']['parent'] == 'pkg:pkg.sub'
    assert module['data']['depth'] == 3
    assert module['data']['label'] == 'mod'


def test_package_chain_is_only_created_once_across_sibling_modules():
    graph = _make_graph([
        {'kind': 'module', 'name': 'pkg.a', 'file': 'pkg/a.py'},
        {'kind': 'module', 'name': 'pkg.b', 'file': 'pkg/b.py'},
    ])

    elements = build_elements(graph)

    package_nodes = [el for el in elements if el['data']['kind'] == 'package']
    assert len(package_nodes) == 1
    assert package_nodes[0]['data']['id'] == 'pkg:pkg'


def test_class_and_method_nest_under_module_and_class():
    graph = _make_graph([
        {'kind': 'module', 'name': 'mod', 'file': 'mod.py'},
        {'kind': 'class', 'name': 'mod.Widget', 'file': 'mod.py', 'lineno': 3, 'end_lineno': 10},
        {'kind': 'function', 'name': 'mod.Widget.render', 'file': 'mod.py', 'lineno': 4, 'end_lineno': 6,
         'complexity': 2, 'loc': 3, 'fan_in': 0, 'fan_out': 0},
    ])

    elements = build_elements(graph)

    widget = _by_id(elements, 'sym:mod.Widget')
    render = _by_id(elements, 'sym:mod.Widget.render')

    assert widget['data']['parent'] == 'mod:mod'
    assert widget['data']['depth'] == 2
    assert render['data']['parent'] == 'sym:mod.Widget'
    assert render['data']['depth'] == 3
    assert render['data']['label'] == 'render'
    assert render['data']['complexity'] == 2


def test_nested_function_nests_under_enclosing_function_not_module():
    graph = _make_graph([
        {'kind': 'module', 'name': 'mod', 'file': 'mod.py'},
        {'kind': 'function', 'name': 'mod.outer', 'file': 'mod.py'},
        {'kind': 'function', 'name': 'mod.outer.inner', 'file': 'mod.py'},
    ])

    elements = build_elements(graph)

    inner = _by_id(elements, 'sym:mod.outer.inner')
    assert inner['data']['parent'] == 'sym:mod.outer'
    assert inner['data']['depth'] == 3


def test_resolved_call_becomes_an_edge_between_symbol_ids():
    graph = _make_graph(
        nodes=[
            {'kind': 'module', 'name': 'mod', 'file': 'mod.py'},
            {'kind': 'function', 'name': 'mod.caller', 'file': 'mod.py'},
            {'kind': 'function', 'name': 'mod.callee', 'file': 'mod.py'},
        ],
        edges=[
            {'caller': 'mod.caller', 'callee': 'mod.callee', 'resolved': True},
        ],
    )

    elements = build_elements(graph)

    call_edges = [el for el in elements if el['data'].get('kind') == 'call']
    assert len(call_edges) == 1
    assert call_edges[0]['data']['source'] == 'sym:mod.caller'
    assert call_edges[0]['data']['target'] == 'sym:mod.callee'


def test_unresolved_call_produces_no_edge():
    graph = _make_graph(
        nodes=[
            {'kind': 'module', 'name': 'mod', 'file': 'mod.py'},
            {'kind': 'function', 'name': 'mod.caller', 'file': 'mod.py'},
        ],
        edges=[
            {'caller': 'mod.caller', 'callee': None, 'resolved': False},
        ],
    )

    elements = build_elements(graph)

    assert not [el for el in elements if el['data'].get('kind') == 'call']


def test_duplicate_calls_to_the_same_callee_collapse_to_one_edge():
    graph = _make_graph(
        nodes=[
            {'kind': 'module', 'name': 'mod', 'file': 'mod.py'},
            {'kind': 'function', 'name': 'mod.caller', 'file': 'mod.py'},
            {'kind': 'function', 'name': 'mod.callee', 'file': 'mod.py'},
        ],
        edges=[
            {'caller': 'mod.caller', 'callee': 'mod.callee', 'resolved': True},
            {'caller': 'mod.caller', 'callee': 'mod.callee', 'resolved': True},
        ],
    )

    elements = build_elements(graph)

    call_edges = [el for el in elements if el['data'].get('kind') == 'call']
    assert len(call_edges) == 1


def test_self_recursive_call_produces_a_self_loop_edge():
    graph = _make_graph(
        nodes=[
            {'kind': 'module', 'name': 'mod', 'file': 'mod.py'},
            {'kind': 'function', 'name': 'mod.recurse', 'file': 'mod.py'},
        ],
        edges=[
            {'caller': 'mod.recurse', 'callee': 'mod.recurse', 'resolved': True},
        ],
    )

    elements = build_elements(graph)

    call_edges = [el for el in elements if el['data'].get('kind') == 'call']
    assert len(call_edges) == 1
    assert call_edges[0]['data']['source'] == call_edges[0]['data']['target'] == 'sym:mod.recurse'


def test_children_of_returns_only_direct_children():
    graph = _make_graph([
        {'kind': 'module', 'name': 'mod', 'file': 'mod.py'},
        {'kind': 'class', 'name': 'mod.Widget', 'file': 'mod.py'},
        {'kind': 'function', 'name': 'mod.Widget.render', 'file': 'mod.py'},
    ])

    elements = build_elements(graph)

    module_children = children_of(elements, 'mod:mod')
    assert [c['data']['id'] for c in module_children] == ['sym:mod.Widget']

    widget_children = children_of(elements, 'sym:mod.Widget')
    assert [c['data']['id'] for c in widget_children] == ['sym:mod.Widget.render']
