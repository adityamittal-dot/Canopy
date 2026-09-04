from explorer.dash_apps import (
    _compute_navigation_update, _resolve_navigation_target, _resolve_search_target, render_detail_panel,
    render_visible_elements,
)
from explorer.graph_data import build_elements, noise_ids


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

    visible = render_visible_elements(elements, [], [], [])

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

    visible = render_visible_elements(elements, [], [], [])

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

    before = render_visible_elements(elements, [], [], [])
    assert 'sym:mod.Widget.render' not in {el['data']['id'] for el in before}

    after = render_visible_elements(elements, ['sym:mod.Widget'], [], [])
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

    hidden = render_visible_elements(elements, [], ['show'], [])
    assert not [el for el in hidden if el['data'].get('kind') == 'call']

    expanded = render_visible_elements(elements, ['sym:mod.Widget'], ['show'], [])
    call_edges = [el for el in expanded if el['data'].get('kind') == 'call']
    assert len(call_edges) == 1


def test_resolve_navigation_target_from_a_direct_graph_tap():
    assert _resolve_navigation_target('repo-graph', None, {'id': 'sym:mod.Widget'}) == 'sym:mod.Widget'


def test_resolve_navigation_target_from_an_untapped_graph_event():
    assert _resolve_navigation_target('repo-graph', None, None) is None


def test_resolve_navigation_target_from_a_real_nav_button_click():
    triggered_id = {'type': 'nav-btn', 'role': 'caller', 'target': 'sym:mod.Widget.render'}
    assert _resolve_navigation_target(triggered_id, 1, None) == 'sym:mod.Widget.render'


def test_resolve_navigation_target_from_a_callee_button_click():
    triggered_id = {'type': 'nav-btn', 'role': 'callee', 'target': 'sym:mod.Widget.render'}
    assert _resolve_navigation_target(triggered_id, 1, None) == 'sym:mod.Widget.render'


def test_resolve_navigation_target_ignores_a_freshly_mounted_unclicked_nav_button():
    # Dash's ALL-pattern-matching Input re-fires this callback whenever the
    # *set* of matched nav-btn components changes (e.g. render_detail_panel
    # mounting a fresh batch for a newly-selected node), not just on a real
    # click - the freshly-mounted button's n_clicks is still its initial 0
    # in that case, which is exactly what this must NOT treat as a click.
    triggered_id = {'type': 'nav-btn', 'role': 'callee', 'target': 'sym:mod.Widget.render'}
    assert _resolve_navigation_target(triggered_id, 0, None) is None
    assert _resolve_navigation_target(triggered_id, None, None) is None


def test_resolve_navigation_target_returns_none_for_anything_else():
    assert _resolve_navigation_target(None, None, None) is None
    assert _resolve_navigation_target('some-other-component', 1, {'id': 'x'}) is None


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


def test_compute_navigation_update_also_reveals_callers_and_callees():
    # Cross-cutting "who calls this, anywhere in the repo": selecting a
    # node should also reveal its callers/callees, not just its own
    # ancestors/children.
    graph = _make_graph(
        nodes=[
            {'kind': 'module', 'name': 'mod', 'file': 'mod.py'},
            {'kind': 'class', 'name': 'mod.Caller', 'file': 'mod.py'},
            {'kind': 'function', 'name': 'mod.Caller.run', 'file': 'mod.py'},
            {'kind': 'class', 'name': 'mod.Target', 'file': 'mod.py'},
            {'kind': 'function', 'name': 'mod.Target.act', 'file': 'mod.py'},
            {'kind': 'class', 'name': 'mod.Callee', 'file': 'mod.py'},
            {'kind': 'function', 'name': 'mod.Callee.done', 'file': 'mod.py'},
        ],
        edges=[
            {'caller': 'mod.Caller.run', 'callee': 'mod.Target.act', 'resolved': True},
            {'caller': 'mod.Target.act', 'callee': 'mod.Callee.done', 'resolved': True},
        ],
    )
    elements = build_elements(graph)

    new_expanded, selected_id = _compute_navigation_update('sym:mod.Target.act', [], elements)

    assert selected_id == 'sym:mod.Target.act'
    # the target's own ancestor (mod:mod, sym:mod.Target), plus the
    # ancestors of its caller (sym:mod.Caller) and its callee (sym:mod.Callee)
    assert set(new_expanded) == {'mod:mod', 'sym:mod.Target', 'sym:mod.Caller', 'sym:mod.Callee'}


def test_compute_navigation_update_dedupes_shared_ancestors_of_multiple_callees():
    graph = _make_graph(
        nodes=[
            {'kind': 'module', 'name': 'mod', 'file': 'mod.py'},
            {'kind': 'class', 'name': 'mod.Widget', 'file': 'mod.py'},
            {'kind': 'function', 'name': 'mod.Widget.a', 'file': 'mod.py'},
            {'kind': 'function', 'name': 'mod.Widget.b', 'file': 'mod.py'},
            {'kind': 'function', 'name': 'mod.Widget.c', 'file': 'mod.py'},
        ],
        edges=[
            # a calls both b and c, both siblings under the same class
            {'caller': 'mod.Widget.a', 'callee': 'mod.Widget.b', 'resolved': True},
            {'caller': 'mod.Widget.a', 'callee': 'mod.Widget.c', 'resolved': True},
        ],
    )
    elements = build_elements(graph)

    new_expanded, selected_id = _compute_navigation_update('sym:mod.Widget.a', [], elements)

    # sym:mod.Widget is the shared ancestor of both callees - must appear once
    assert new_expanded.count('sym:mod.Widget') == 1
    assert new_expanded.count('mod:mod') == 1


def test_render_visible_elements_hides_noise_when_toggle_is_on():
    graph = _make_graph([
        {'kind': 'module', 'name': 'pkg.mod', 'file': 'pkg/mod.py', 'relative_path': 'pkg/mod.py'},
        {'kind': 'module', 'name': 'tests.test_mod', 'file': 'tests/test_mod.py', 'relative_path': 'tests/test_mod.py'},
    ])
    elements = build_elements(graph)

    hidden = render_visible_elements(elements, [], [], ['hide'])
    visible_ids = {el['data']['id'] for el in hidden}
    assert 'mod:pkg.mod' in visible_ids
    assert 'mod:tests.test_mod' not in visible_ids
    assert 'pkg:tests' not in visible_ids

    shown = render_visible_elements(elements, [], [], [])
    visible_ids = {el['data']['id'] for el in shown}
    assert 'mod:tests.test_mod' in visible_ids


def test_render_visible_elements_noise_stays_hidden_even_if_previously_expanded():
    # e.g. the user expanded the tests package before turning the filter on.
    graph = _make_graph([
        {'kind': 'module', 'name': 'tests.test_mod', 'file': 'tests/test_mod.py', 'relative_path': 'tests/test_mod.py'},
        {'kind': 'function', 'name': 'tests.test_mod.test_it', 'file': 'tests/test_mod.py',
         'relative_path': 'tests/test_mod.py'},
    ])
    elements = build_elements(graph)

    visible = render_visible_elements(elements, ['pkg:tests', 'mod:tests.test_mod'], [], ['hide'])

    _assert_no_dangling_parents(visible)
    visible_ids = {el['data']['id'] for el in visible}
    assert 'pkg:tests' not in visible_ids
    assert 'mod:tests.test_mod' not in visible_ids
    assert 'sym:tests.test_mod.test_it' not in visible_ids


def test_resolve_search_target_prefers_an_exact_label_match():
    graph = _make_graph([
        {'kind': 'module', 'name': 'mod', 'file': 'mod.py'},
        {'kind': 'function', 'name': 'mod.add', 'file': 'mod.py'},
        {'kind': 'function', 'name': 'mod.add_all_things', 'file': 'mod.py'},
    ])
    elements = build_elements(graph)

    target_id, message = _resolve_search_target('add', elements, excluded_ids=set())

    assert target_id == 'sym:mod.add'
    assert 'other match' in message


def test_resolve_search_target_falls_back_to_shortest_name_among_substring_matches():
    graph = _make_graph([
        {'kind': 'module', 'name': 'mod', 'file': 'mod.py'},
        {'kind': 'function', 'name': 'mod.addendum', 'file': 'mod.py'},
        {'kind': 'function', 'name': 'mod.add_all_the_things', 'file': 'mod.py'},
    ])
    elements = build_elements(graph)

    target_id, _ = _resolve_search_target('add', elements, excluded_ids=set())

    assert target_id == 'sym:mod.addendum'


def test_resolve_search_target_reports_no_match():
    graph = _make_graph([{'kind': 'module', 'name': 'mod', 'file': 'mod.py'}])
    elements = build_elements(graph)

    target_id, message = _resolve_search_target('nonexistent', elements, excluded_ids=set())

    assert target_id is None
    assert 'No match' in message


def test_resolve_search_target_prompts_for_an_empty_query():
    target_id, message = _resolve_search_target('   ', [], excluded_ids=set())

    assert target_id is None
    assert message == 'Enter a search term.'


def test_resolve_search_target_excludes_noise_ids():
    graph = _make_graph([
        {'kind': 'module', 'name': 'tests.test_add', 'file': 'tests/test_add.py',
         'relative_path': 'tests/test_add.py'},
        {'kind': 'function', 'name': 'tests.test_add.test_add', 'file': 'tests/test_add.py',
         'relative_path': 'tests/test_add.py'},
    ])
    elements = build_elements(graph)
    excluded = noise_ids(elements)
    assert excluded == {'pkg:tests', 'mod:tests.test_add', 'sym:tests.test_add.test_add'}  # sanity on the premise

    target_id, message = _resolve_search_target('add', elements, excluded_ids=excluded)

    assert target_id is None
    assert 'No match' in message


def test_resolve_search_target_ignores_package_and_repo_nodes():
    # A repo's own name can't coincidentally appear as a substring of any
    # module/class/function name here - unlike a package name, which
    # always IS a substring of every module nested under it by
    # construction, so it can't isolate this case on its own.
    graph = _make_graph([
        {'kind': 'module', 'name': 'pkg.mod', 'file': 'pkg/mod.py'},
    ])
    elements = build_elements(graph, repo_label='distinctive-repo-name')

    target_id, message = _resolve_search_target('distinctive-repo-name', elements, excluded_ids=set())

    assert target_id is None
    assert 'No match' in message


def _panel_text(rows):
    texts = []
    for row in rows:
        children = getattr(row, 'children', None)
        if isinstance(children, str):
            texts.append(children)
        elif isinstance(children, list):
            for child in children:
                label = getattr(child, 'children', None)
                if isinstance(label, str):
                    texts.append(label)
    return texts


def test_render_detail_panel_excludes_noise_callers_and_callees_when_filter_is_on():
    graph = _make_graph(
        nodes=[
            {'kind': 'module', 'name': 'mod', 'file': 'mod.py'},
            {'kind': 'function', 'name': 'mod.real_func', 'file': 'mod.py'},
            {'kind': 'module', 'name': 'tests.test_mod', 'file': 'tests/test_mod.py',
             'relative_path': 'tests/test_mod.py'},
            {'kind': 'function', 'name': 'tests.test_mod.test_real_func', 'file': 'tests/test_mod.py',
             'relative_path': 'tests/test_mod.py'},
        ],
        edges=[
            {'caller': 'tests.test_mod.test_real_func', 'callee': 'mod.real_func', 'resolved': True},
        ],
    )
    elements = build_elements(graph)

    with_filter = render_detail_panel('sym:mod.real_func', ['hide'], elements, {})
    assert 'Called by:' not in _panel_text(with_filter)

    without_filter = render_detail_panel('sym:mod.real_func', [], elements, {})
    assert 'Called by:' in _panel_text(without_filter)
