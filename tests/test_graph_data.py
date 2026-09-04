from explorer.graph_data import (
    ancestors_of, build_elements, callers_and_callees, children_of, index_children, noise_ids_for_tests,
    subtree_node_count, vendor_noise_ids,
)


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


def test_index_children_matches_children_of_for_every_parent():
    graph = _make_graph([
        {'kind': 'module', 'name': 'mod', 'file': 'mod.py'},
        {'kind': 'class', 'name': 'mod.Widget', 'file': 'mod.py'},
        {'kind': 'function', 'name': 'mod.Widget.render', 'file': 'mod.py'},
        {'kind': 'function', 'name': 'mod.top_level', 'file': 'mod.py'},
    ])

    elements = build_elements(graph)
    index = index_children(elements)

    for el in elements:
        parent_id = el['data']['id']
        assert index.get(parent_id, []) == children_of(elements, parent_id)


def test_same_named_symbols_like_a_property_getter_and_setter_get_distinct_ids():
    # parsing.extract does not merge @property getter/setter/deleter pairs -
    # both are recorded as separate `function` symbols named `mod.Widget.x`.
    graph = _make_graph([
        {'kind': 'module', 'name': 'mod', 'file': 'mod.py'},
        {'kind': 'class', 'name': 'mod.Widget', 'file': 'mod.py'},
        {'kind': 'function', 'name': 'mod.Widget.x', 'file': 'mod.py', 'lineno': 2},
        {'kind': 'function', 'name': 'mod.Widget.x', 'file': 'mod.py', 'lineno': 6},
    ])

    elements = build_elements(graph)

    x_elements = [el for el in elements if el['data']['label'] == 'x']
    assert len(x_elements) == 2

    ids = {el['data']['id'] for el in x_elements}
    assert len(ids) == 2  # unique - Cytoscape requires distinct element ids
    assert 'sym:mod.Widget.x' in ids
    assert 'sym:mod.Widget.x#2' in ids

    linenos = {el['data']['lineno'] for el in x_elements}
    assert linenos == {2, 6}  # both occurrences kept, neither dropped


def test_relative_path_passes_through_from_the_pipeline_node_unchanged():
    # relative_path is computed once by parsing.pipeline (single source of
    # truth - see tests/test_pipeline.py) and just carried through here.
    graph = _make_graph([
        {'kind': 'module', 'name': 'pkg.mod', 'file': '/tmp/abc123/pkg/mod.py', 'relative_path': 'pkg/mod.py'},
        {'kind': 'function', 'name': 'pkg.mod.f', 'file': '/tmp/abc123/pkg/mod.py', 'relative_path': 'pkg/mod.py'},
    ])
    elements = build_elements(graph)

    assert _by_id(elements, 'mod:pkg.mod')['data']['relative_path'] == 'pkg/mod.py'
    assert _by_id(elements, 'sym:pkg.mod.f')['data']['relative_path'] == 'pkg/mod.py'


def test_relative_path_is_none_when_the_pipeline_node_lacks_it():
    graph = _make_graph([
        {'kind': 'module', 'name': 'mod', 'file': 'mod.py'},
    ])
    elements = build_elements(graph)

    assert _by_id(elements, 'mod:mod')['data']['relative_path'] is None


def test_ancestors_of_walks_up_to_but_excludes_repo():
    graph = _make_graph([
        {'kind': 'module', 'name': 'pkg.mod', 'file': 'pkg/mod.py'},
        {'kind': 'class', 'name': 'pkg.mod.Widget', 'file': 'pkg/mod.py'},
        {'kind': 'function', 'name': 'pkg.mod.Widget.render', 'file': 'pkg/mod.py'},
    ])
    elements = build_elements(graph)

    assert ancestors_of(elements, 'sym:pkg.mod.Widget.render') == [
        'sym:pkg.mod.Widget', 'mod:pkg.mod', 'pkg:pkg',
    ]
    assert ancestors_of(elements, 'pkg:pkg') == []


def test_callers_and_callees_reads_off_the_call_edges():
    graph = _make_graph(
        nodes=[
            {'kind': 'module', 'name': 'mod', 'file': 'mod.py'},
            {'kind': 'function', 'name': 'mod.a', 'file': 'mod.py'},
            {'kind': 'function', 'name': 'mod.b', 'file': 'mod.py'},
            {'kind': 'function', 'name': 'mod.c', 'file': 'mod.py'},
        ],
        edges=[
            {'caller': 'mod.a', 'callee': 'mod.b', 'resolved': True},
            {'caller': 'mod.c', 'callee': 'mod.b', 'resolved': True},
            {'caller': 'mod.b', 'callee': 'mod.c', 'resolved': True},
        ],
    )
    elements = build_elements(graph)

    callers, callees = callers_and_callees(elements, 'sym:mod.b')
    assert sorted(callers) == ['sym:mod.a', 'sym:mod.c']
    assert callees == ['sym:mod.c']

    no_callers, no_callees = callers_and_callees(elements, 'sym:mod.a')
    assert no_callers == []
    assert no_callees == ['sym:mod.b']


def test_test_noise_ids_is_empty_for_a_repo_with_no_test_code():
    graph = _make_graph([
        {'kind': 'module', 'name': 'pkg.mod', 'file': 'pkg/mod.py', 'relative_path': 'pkg/mod.py'},
        {'kind': 'function', 'name': 'pkg.mod.f', 'file': 'pkg/mod.py', 'relative_path': 'pkg/mod.py'},
    ])
    elements = build_elements(graph)

    assert noise_ids_for_tests(elements) == set()
    assert vendor_noise_ids(elements) == set()


def test_test_noise_ids_marks_a_tests_package_and_everything_under_it():
    graph = _make_graph([
        {'kind': 'module', 'name': 'tests.test_widget', 'file': 'tests/test_widget.py',
         'relative_path': 'tests/test_widget.py'},
        {'kind': 'function', 'name': 'tests.test_widget.test_it_works', 'file': 'tests/test_widget.py',
         'relative_path': 'tests/test_widget.py'},
        {'kind': 'module', 'name': 'pkg.mod', 'file': 'pkg/mod.py', 'relative_path': 'pkg/mod.py'},
    ])
    elements = build_elements(graph)

    noise = noise_ids_for_tests(elements)
    assert 'pkg:tests' in noise
    assert 'mod:tests.test_widget' in noise
    assert 'sym:tests.test_widget.test_it_works' in noise
    assert 'mod:pkg.mod' not in noise
    assert 'pkg:pkg' not in noise
    assert vendor_noise_ids(elements) == set()


def test_test_noise_ids_marks_a_test_module_outside_a_tests_package():
    # e.g. a top-level test_something.py without a dedicated tests/ package
    graph = _make_graph([
        {'kind': 'module', 'name': 'test_widget', 'file': 'test_widget.py', 'relative_path': 'test_widget.py'},
        {'kind': 'function', 'name': 'test_widget.test_it_works', 'file': 'test_widget.py',
         'relative_path': 'test_widget.py'},
    ])
    elements = build_elements(graph)

    noise = noise_ids_for_tests(elements)
    assert 'mod:test_widget' in noise
    assert 'sym:test_widget.test_it_works' in noise


def test_vendor_noise_ids_marks_a_vendor_package_but_not_test_noise_ids():
    graph = _make_graph([
        {'kind': 'module', 'name': 'vendor.requests.api', 'file': 'vendor/requests/api.py',
         'relative_path': 'vendor/requests/api.py'},
    ])
    elements = build_elements(graph)

    noise = vendor_noise_ids(elements)
    assert 'pkg:vendor' in noise
    assert 'pkg:vendor.requests' in noise
    assert 'mod:vendor.requests.api' in noise
    assert noise_ids_for_tests(elements) == set()


def test_noise_ids_are_case_insensitive():
    graph = _make_graph([
        {'kind': 'module', 'name': 'Tests.test_widget', 'file': 'Tests/test_widget.py',
         'relative_path': 'Tests/test_widget.py'},
    ])
    elements = build_elements(graph)

    assert 'pkg:Tests' in noise_ids_for_tests(elements)


def test_noise_ids_do_not_flag_a_module_that_merely_contains_test_as_a_substring():
    # "latest.py" or a "testament" package should not be treated as noise -
    # only an exact "test"/"tests"/"testing" segment, or a test_*.py/*_test.py
    # filename convention, counts.
    graph = _make_graph([
        {'kind': 'module', 'name': 'latest', 'file': 'latest.py', 'relative_path': 'latest.py'},
        {'kind': 'module', 'name': 'testament.mod', 'file': 'testament/mod.py', 'relative_path': 'testament/mod.py'},
    ])
    elements = build_elements(graph)

    assert noise_ids_for_tests(elements) == set()
    assert vendor_noise_ids(elements) == set()


def test_subtree_node_count_includes_self_and_all_descendants():
    graph = _make_graph([
        {'kind': 'module', 'name': 'pkg.mod', 'file': 'pkg/mod.py', 'relative_path': 'pkg/mod.py'},
        {'kind': 'class', 'name': 'pkg.mod.Widget', 'file': 'pkg/mod.py', 'relative_path': 'pkg/mod.py'},
        {'kind': 'function', 'name': 'pkg.mod.Widget.render', 'file': 'pkg/mod.py', 'relative_path': 'pkg/mod.py'},
        {'kind': 'function', 'name': 'pkg.mod.top_level', 'file': 'pkg/mod.py', 'relative_path': 'pkg/mod.py'},
    ])
    elements = build_elements(graph)

    # the module itself, the class, and both functions
    assert subtree_node_count(elements, 'mod:pkg.mod') == 4
    assert subtree_node_count(elements, 'sym:pkg.mod.Widget') == 2
    assert subtree_node_count(elements, 'sym:pkg.mod.Widget.render') == 1


def test_subtree_node_count_does_not_count_synthetic_package_containers():
    graph = _make_graph([
        {'kind': 'module', 'name': 'pkg.sub.mod', 'file': 'pkg/sub/mod.py', 'relative_path': 'pkg/sub/mod.py'},
    ])
    elements = build_elements(graph)

    # 'pkg' and 'pkg.sub' are synthetic containers, not real symbols
    assert subtree_node_count(elements, 'pkg:pkg') == 1
