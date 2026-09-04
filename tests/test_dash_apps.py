from explorer.dash_apps import _compute_navigation_update, _resolve_navigation_target, render_visible_elements
from explorer.graph_data import build_elements


def _make_graph(nodes, edges=()):
    return {'nodes': nodes, 'edges': list(edges)}


def _assert_no_dangling_parents(elements):
    ids = {el['data']['id'] for el in elements}
    for el in elements:
        if el['data'].get('kind') == 'call':
            continue
        parent_id = el['data'].get('parent')
        assert parent_id is None or parent_id in ids, (
            f"element {el['data']['id']!r} has parent {parent_id!r} which isn't in the visible set"
        )


def test_leaf_functions_are_hidden_by_default():
    graph = _make_graph([
        {'kind': 'module', 'name': 'mod', 'file': 'mod.py'},
        {'kind': 'function', 'name': 'mod.leaf', 'file': 'mod.py'},
    ])
    elements = build_elements(graph)

    visible = render_visible_elements(elements, [], [])

    _assert_no_dangling_parents(visible)
    assert 'sym:mod.leaf' not in {el['data']['id'] for el in visible}


def test_a_function_containing_a_nested_class_stays_visible_by_default():
    # e.g. a factory function that defines and returns a local class - a
    # legal Python pattern that parsing.extract records with the function
    # as the class's qualified-name parent.
    graph = _make_graph([
        {'kind': 'module', 'name': 'mod', 'file': 'mod.py'},
        {'kind': 'function', 'name': 'mod.make_widget', 'file': 'mod.py'},
        {'kind': 'class', 'name': 'mod.make_widget.LocalWidget', 'file': 'mod.py'},
    ])
    elements = build_elements(graph)

    visible = render_visible_elements(elements, [], [])

    _assert_no_dangling_parents(visible)
    visible_ids = {el['data']['id'] for el in visible}
    assert 'sym:mod.make_widget' in visible_ids  # container function, not a leaf
    assert 'sym:mod.make_widget.LocalWidget' in visible_ids


def test_expanding_a_class_reveals_only_its_own_methods():
    graph = _make_graph([
        {'kind': 'module', 'name': 'mod', 'file': 'mod.py'},
        {'kind': 'class', 'name': 'mod.Widget', 'file': 'mod.py'},
        {'kind': 'function', 'name': 'mod.Widget.render', 'file': 'mod.py'},
    ])
    elements = build_elements(graph)

    before = render_visible_elements(elements, [], [])
    assert 'sym:mod.Widget.render' not in {el['data']['id'] for el in before}

    after = render_visible_elements(elements, ['sym:mod.Widget'], [])
    _assert_no_dangling_parents(after)
    assert 'sym:mod.Widget.render' in {el['data']['id'] for el in after}


def test_show_calls_only_includes_edges_between_visible_nodes():
    graph = _make_graph(
        nodes=[
            {'kind': 'module', 'name': 'mod', 'file': 'mod.py'},
            {'kind': 'class', 'name': 'mod.Widget', 'file': 'mod.py'},
            {'kind': 'function', 'name': 'mod.Widget.a', 'file': 'mod.py'},
            {'kind': 'function', 'name': 'mod.Widget.b', 'file': 'mod.py'},
        ],
        edges=[
            {'caller': 'mod.Widget.a', 'callee': 'mod.Widget.b', 'resolved': True},
        ],
    )
    elements = build_elements(graph)

    hidden = render_visible_elements(elements, [], ['show'])
    assert not [el for el in hidden if el['data'].get('kind') == 'call']

    expanded = render_visible_elements(elements, ['sym:mod.Widget'], ['show'])
    call_edges = [el for el in expanded if el['data'].get('kind') == 'call']
    assert len(call_edges) == 1


def test_resolve_navigation_target_from_a_direct_graph_tap():
    assert _resolve_navigation_target('repo-graph', {'id': 'sym:mod.Widget'}) == 'sym:mod.Widget'


def test_resolve_navigation_target_from_an_untapped_graph_event():
    assert _resolve_navigation_target('repo-graph', None) is None


def test_resolve_navigation_target_from_a_nav_button():
    triggered_id = {'type': 'nav-btn', 'index': 'caller:sym:mod.Widget.render'}
    assert _resolve_navigation_target(triggered_id, None) == 'sym:mod.Widget.render'


def test_resolve_navigation_target_from_a_callee_button_with_a_colon_in_the_id():
    # target ids themselves contain colons (e.g. "sym:..."), so the role
    # prefix must only ever strip the first colon, not split on all of them.
    triggered_id = {'type': 'nav-btn', 'index': 'callee:sym:mod.Widget.render'}
    assert _resolve_navigation_target(triggered_id, None) == 'sym:mod.Widget.render'


def test_resolve_navigation_target_returns_none_for_anything_else():
    assert _resolve_navigation_target(None, None) is None
    assert _resolve_navigation_target('some-other-component', {'id': 'x'}) is None


def test_compute_navigation_update_reveals_ancestors_of_an_unexpanded_target():
    graph = _make_graph([
        {'kind': 'module', 'name': 'mod', 'file': 'mod.py'},
        {'kind': 'class', 'name': 'mod.Widget', 'file': 'mod.py'},
        {'kind': 'function', 'name': 'mod.Widget.render', 'file': 'mod.py'},
    ])
    elements = build_elements(graph)

    new_expanded, selected_id = _compute_navigation_update('sym:mod.Widget.render', [], elements)

    assert selected_id == 'sym:mod.Widget.render'
    # both ancestors need revealing - render itself has no children of its own, so it isn't added
    assert set(new_expanded) == {'sym:mod.Widget', 'mod:mod'}
    assert 'sym:mod.Widget.render' not in new_expanded


def test_compute_navigation_update_also_expands_a_container_target_to_show_its_children():
    graph = _make_graph([
        {'kind': 'module', 'name': 'mod', 'file': 'mod.py'},
        {'kind': 'class', 'name': 'mod.Widget', 'file': 'mod.py'},
        {'kind': 'function', 'name': 'mod.Widget.render', 'file': 'mod.py'},
    ])
    elements = build_elements(graph)

    new_expanded, selected_id = _compute_navigation_update('sym:mod.Widget', [], elements)

    assert selected_id == 'sym:mod.Widget'
    # the class's own ancestor (the module) plus the class itself, so its children (render) show too
    assert set(new_expanded) == {'mod:mod', 'sym:mod.Widget'}


def test_compute_navigation_update_is_a_noop_when_target_and_ancestors_are_already_expanded():
    graph = _make_graph([
        {'kind': 'module', 'name': 'mod', 'file': 'mod.py'},
        {'kind': 'function', 'name': 'mod.leaf', 'file': 'mod.py'},
    ])
    elements = build_elements(graph)

    # mod:mod already expanded (as if the module was clicked before), and
    # mod.leaf has no children of its own - navigating to it again should
    # need no further changes.
    new_expanded, selected_id = _compute_navigation_update('sym:mod.leaf', ['mod:mod'], elements)

    assert selected_id == 'sym:mod.leaf'
    assert new_expanded is None


def test_compute_navigation_update_returns_none_none_for_no_target():
    assert _compute_navigation_update(None, [], []) == (None, None)
