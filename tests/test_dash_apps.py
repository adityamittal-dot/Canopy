from explorer.dash_apps import (
    _find_element, _parse_triggered, _resolve_click, _resolve_search, _resolve_search_target, _reveal_target,
    _toggle_membership, render_breadcrumb, render_detail_panel, render_toast, render_tree,
)
from explorer.graph_data import build_elements


def _make_graph(nodes, edges=()):
    return {'nodes': nodes, 'edges': list(edges)}


# --- _parse_triggered -----------------------------------------------------------
# django-plotly-dash's CallbackContext shim doesn't implement Dash's
# `triggered_id` property (confirmed via a live click through a real
# browser - it raised AttributeError in production, not just a lint
# warning), so this hand-parses `.triggered` instead. These tests use the
# exact shapes Dash's own `.triggered` list takes.

def test_parse_triggered_returns_none_none_for_an_empty_list():
    assert _parse_triggered([]) == (None, None)


def test_parse_triggered_parses_a_simple_component_id():
    triggered = [{'prop_id': 'search-input.n_submit', 'value': 1}]
    assert _parse_triggered(triggered) == ('search-input', 1)


def test_parse_triggered_parses_a_pattern_matching_dict_id():
    triggered = [{'prop_id': '{"action":"select","id":"pkg:docs","type":"cy-click"}.n_clicks', 'value': 1}]
    assert _parse_triggered(triggered) == ({'action': 'select', 'id': 'pkg:docs', 'type': 'cy-click'}, 1)


def test_parse_triggered_preserves_a_falsy_value_for_the_mount_vs_click_guard():
    # a freshly-mounted (never clicked) button reports n_clicks as 0 or
    # None, not absent - callers rely on that falsy value surviving here.
    triggered = [{'prop_id': '{"action":"expand","id":"mod:mod","type":"cy-click"}.n_clicks', 'value': None}]
    assert _parse_triggered(triggered) == ({'action': 'expand', 'id': 'mod:mod', 'type': 'cy-click'}, None)


def _all_box_and_pill_ids(component):
    """Recursively collect every {'type': 'cy-click', ...} component id found
    in a rendered Dash component tree, for asserting what actually rendered."""
    ids = []
    node_id = getattr(component, 'id', None)
    if isinstance(node_id, dict) and node_id.get('type') == 'cy-click':
        ids.append(node_id['id'])
    for child in getattr(component, 'children', None) or []:
        if hasattr(child, 'children') or hasattr(child, 'id'):
            ids.extend(_all_box_and_pill_ids(child))
    return ids


def _render_text(component):
    """Flatten all string children out of a rendered Dash component tree."""
    texts = []
    children = getattr(component, 'children', None)
    if isinstance(children, str):
        texts.append(children)
    elif isinstance(children, (list, tuple)):
        for child in children:
            if isinstance(child, str):
                texts.append(child)
            else:
                texts.extend(_render_text(child))
    elif children is not None:
        texts.extend(_render_text(children))
    return texts


# --- _find_element -----------------------------------------------------------

def test_find_element_returns_none_for_a_missing_id():
    assert _find_element([], 'sym:missing') is None


def test_find_element_returns_the_matching_element():
    graph = _make_graph([{'kind': 'module', 'name': 'mod', 'file': 'mod.py'}])
    elements = build_elements(graph)
    assert _find_element(elements, 'mod:mod')['data']['label'] == 'mod'


# --- _reveal_target ------------------------------------------------------------

def test_reveal_target_reveals_an_unexpanded_functions_parent():
    graph = _make_graph([
        {'kind': 'module', 'name': 'mod', 'file': 'mod.py'},
        {'kind': 'class', 'name': 'mod.Widget', 'file': 'mod.py'},
        {'kind': 'function', 'name': 'mod.Widget.render', 'file': 'mod.py'},
    ])
    elements = build_elements(graph)

    new_expanded = _reveal_target('sym:mod.Widget.render', [], elements)

    assert new_expanded == ['sym:mod.Widget']


def test_reveal_target_is_a_noop_when_parent_already_expanded():
    graph = _make_graph([
        {'kind': 'module', 'name': 'mod', 'file': 'mod.py'},
        {'kind': 'function', 'name': 'mod.f', 'file': 'mod.py'},
    ])
    elements = build_elements(graph)

    assert _reveal_target('sym:mod.f', ['mod:mod'], elements) is None


def test_reveal_target_is_a_noop_for_non_function_targets():
    # packages/modules/classes are always rendered - nothing to reveal.
    graph = _make_graph([
        {'kind': 'module', 'name': 'pkg.mod', 'file': 'pkg/mod.py'},
    ])
    elements = build_elements(graph)

    assert _reveal_target('mod:pkg.mod', [], elements) is None
    assert _reveal_target('pkg:pkg', [], elements) is None


# --- _toggle_membership / _resolve_click ----------------------------------------

def test_toggle_membership_adds_then_removes():
    assert _toggle_membership([], 'a') == ['a']
    assert _toggle_membership(['a'], 'a') == []
    assert _toggle_membership(['a'], 'b') == ['a', 'b']


def test_resolve_click_expand_toggles_expanded_list_and_leaves_selection_alone():
    new_expanded, new_selected = _resolve_click('expand', 'mod:mod', [], [], 'sym:something')
    assert new_expanded == ['mod:mod']
    assert new_selected is None

    new_expanded, new_selected = _resolve_click('expand', 'mod:mod', ['mod:mod'], [], 'sym:something')
    assert new_expanded == []
    assert new_selected is None


def test_resolve_click_select_is_a_noop_when_already_selected():
    assert _resolve_click('select', 'mod:mod', [], [], 'mod:mod') == (None, None)


def test_resolve_click_select_just_selects_without_touching_expanded():
    new_expanded, new_selected = _resolve_click('select', 'mod:mod', ['x'], [], None)
    assert new_expanded is None
    assert new_selected == 'mod:mod'


def test_resolve_click_navigate_reveals_and_selects_a_function():
    graph = _make_graph([
        {'kind': 'module', 'name': 'mod', 'file': 'mod.py'},
        {'kind': 'function', 'name': 'mod.f', 'file': 'mod.py'},
    ])
    elements = build_elements(graph)

    new_expanded, new_selected = _resolve_click('navigate', 'sym:mod.f', [], elements, None)
    assert new_expanded == ['mod:mod']
    assert new_selected == 'sym:mod.f'


def test_resolve_click_unknown_action_is_a_noop():
    assert _resolve_click('bogus', 'x', [], [], None) == (None, None)


# --- _resolve_search_target ----------------------------------------------------

def test_resolve_search_target_prefers_an_exact_label_match():
    graph = _make_graph([
        {'kind': 'module', 'name': 'mod', 'file': 'mod.py'},
        {'kind': 'function', 'name': 'mod.add', 'file': 'mod.py'},
        {'kind': 'function', 'name': 'mod.add_all_things', 'file': 'mod.py'},
    ])
    elements = build_elements(graph)

    assert _resolve_search_target('add', elements, excluded_ids=set()) == 'sym:mod.add'


def test_resolve_search_target_falls_back_to_shortest_name_among_matches():
    graph = _make_graph([
        {'kind': 'module', 'name': 'mod', 'file': 'mod.py'},
        {'kind': 'function', 'name': 'mod.addendum', 'file': 'mod.py'},
        {'kind': 'function', 'name': 'mod.add_all_the_things', 'file': 'mod.py'},
    ])
    elements = build_elements(graph)

    assert _resolve_search_target('add', elements, excluded_ids=set()) == 'sym:mod.addendum'


def test_resolve_search_target_returns_none_for_no_match():
    graph = _make_graph([{'kind': 'module', 'name': 'mod', 'file': 'mod.py'}])
    elements = build_elements(graph)

    assert _resolve_search_target('nonexistent', elements, excluded_ids=set()) is None


def test_resolve_search_target_returns_none_for_an_empty_query():
    assert _resolve_search_target('   ', [], excluded_ids=set()) is None


def test_resolve_search_target_excludes_given_ids():
    graph = _make_graph([{'kind': 'module', 'name': 'mod', 'file': 'mod.py'}])
    elements = build_elements(graph)

    assert _resolve_search_target('mod', elements, excluded_ids={'mod:mod'}) is None


def test_resolve_search_target_ignores_package_and_repo_nodes():
    graph = _make_graph([{'kind': 'module', 'name': 'pkg.mod', 'file': 'pkg/mod.py'}])
    elements = build_elements(graph, repo_label='distinctive-repo-name')

    assert _resolve_search_target('distinctive-repo-name', elements, excluded_ids=set()) is None


# --- _resolve_search -------------------------------------------------------------

def test_resolve_search_reveals_and_selects_a_match():
    graph = _make_graph([
        {'kind': 'module', 'name': 'mod', 'file': 'mod.py'},
        {'kind': 'function', 'name': 'mod.add', 'file': 'mod.py'},
    ])
    elements = build_elements(graph)

    new_expanded, new_selected = _resolve_search('add', elements, [], None, hide_tests=False, hide_vendor=False)
    assert new_expanded == ['mod:mod']
    assert new_selected == 'sym:mod.add'


def test_resolve_search_respects_hide_tests_exclusion():
    # module name deliberately does not contain "add" itself, so the search
    # term can only match the function - isolating the exclusion being
    # tested from the exact-vs-shortest-name tiebreak covered elsewhere.
    graph = _make_graph([
        {'kind': 'module', 'name': 'tests.helpers', 'file': 'tests/helpers.py', 'relative_path': 'tests/helpers.py'},
        {'kind': 'function', 'name': 'tests.helpers.test_add', 'file': 'tests/helpers.py',
         'relative_path': 'tests/helpers.py'},
    ])
    elements = build_elements(graph)

    new_expanded, new_selected = _resolve_search('add', elements, [], None, hide_tests=True, hide_vendor=False)
    assert (new_expanded, new_selected) == (None, None)

    new_expanded, new_selected = _resolve_search('add', elements, [], None, hide_tests=False, hide_vendor=False)
    assert new_selected == 'sym:tests.helpers.test_add'


def test_resolve_search_is_a_noop_when_target_already_selected():
    graph = _make_graph([
        {'kind': 'module', 'name': 'mod', 'file': 'mod.py'},
        {'kind': 'function', 'name': 'mod.add', 'file': 'mod.py'},
    ])
    elements = build_elements(graph)

    assert _resolve_search('add', elements, [], 'sym:mod.add', hide_tests=False, hide_vendor=False) == (None, None)


# --- render_tree -----------------------------------------------------------------

def test_render_tree_hides_leaf_functions_by_default():
    graph = _make_graph([
        {'kind': 'module', 'name': 'mod', 'file': 'mod.py'},
        {'kind': 'function', 'name': 'mod.f', 'file': 'mod.py'},
    ])
    elements = build_elements(graph)

    tree = render_tree(elements, [], hide_tests=False, hide_vendor=False, selected_id=None)

    assert 'sym:mod.f' not in _all_box_and_pill_ids(tree)


def test_render_tree_reveals_functions_of_an_expanded_class():
    graph = _make_graph([
        {'kind': 'module', 'name': 'mod', 'file': 'mod.py'},
        {'kind': 'class', 'name': 'mod.Widget', 'file': 'mod.py'},
        {'kind': 'function', 'name': 'mod.Widget.render', 'file': 'mod.py'},
    ])
    elements = build_elements(graph)

    tree = render_tree(elements, ['sym:mod.Widget'], hide_tests=False, hide_vendor=False, selected_id=None)

    ids = _all_box_and_pill_ids(tree)
    assert 'mod:mod' in ids
    assert 'sym:mod.Widget' in ids
    assert 'sym:mod.Widget.render' in ids


def test_render_tree_ghosts_a_noise_filtered_package_instead_of_hiding_it():
    graph = _make_graph([
        {'kind': 'module', 'name': 'tests.test_mod', 'file': 'tests/test_mod.py', 'relative_path': 'tests/test_mod.py'},
        {'kind': 'module', 'name': 'pkg.mod', 'file': 'pkg/mod.py', 'relative_path': 'pkg/mod.py'},
    ])
    elements = build_elements(graph)

    tree = render_tree(elements, [], hide_tests=True, hide_vendor=False, selected_id=None)

    text = ' '.join(_render_text(tree))
    assert 'filtered · test' in text
    assert 'mod:tests.test_mod' not in _all_box_and_pill_ids(tree)
    assert 'mod:pkg.mod' in _all_box_and_pill_ids(tree)


def test_render_tree_shows_noise_normally_when_filter_is_off():
    graph = _make_graph([
        {'kind': 'module', 'name': 'tests.test_mod', 'file': 'tests/test_mod.py', 'relative_path': 'tests/test_mod.py'},
    ])
    elements = build_elements(graph)

    tree = render_tree(elements, [], hide_tests=False, hide_vendor=False, selected_id=None)

    assert 'mod:tests.test_mod' in _all_box_and_pill_ids(tree)


def test_render_tree_reports_vendor_filter_with_its_own_label():
    graph = _make_graph([
        {'kind': 'module', 'name': 'vendor.requests', 'file': 'vendor/requests.py', 'relative_path': 'vendor/requests.py'},
    ])
    elements = build_elements(graph)

    tree = render_tree(elements, [], hide_tests=False, hide_vendor=True, selected_id=None)

    text = ' '.join(_render_text(tree))
    assert 'filtered · vendor' in text


def test_render_tree_on_no_elements_shows_a_status_message_not_an_error():
    tree = render_tree([], [], hide_tests=True, hide_vendor=True, selected_id=None)
    assert 'No analysis loaded.' in _render_text(tree)


# --- render_detail_panel -----------------------------------------------------------

_FAKE_REPO_META = {'url': 'https://example.com/not-github', 'commit_hash': 'abc123', 'name': 'demo'}


def test_render_detail_panel_prompts_when_nothing_selected():
    panel = render_detail_panel(None, True, True, True, [], {})
    assert 'Select a node' in ' '.join(_render_text(panel))


def test_render_detail_panel_shows_stats_and_source_only_for_functions():
    graph = _make_graph([
        {'kind': 'module', 'name': 'mod', 'file': 'mod.py', 'relative_path': 'mod.py'},
        {'kind': 'function', 'name': 'mod.f', 'file': 'mod.py', 'relative_path': 'mod.py', 'lineno': 1, 'end_lineno': 2,
         'loc': 2, 'complexity': 1, 'fan_in': 0, 'fan_out': 0},
    ])
    elements = build_elements(graph)

    module_panel = render_detail_panel('mod:mod', True, False, False, elements, _FAKE_REPO_META)
    module_text = ' '.join(str(t) for t in _flatten_panel(module_panel))
    assert 'ccyc' not in module_text  # no stats grid for a module

    fn_panel = render_detail_panel('sym:mod.f', True, False, False, elements, _FAKE_REPO_META)
    fn_text = ' '.join(str(t) for t in _flatten_panel(fn_panel))
    assert 'ccyc' in fn_text
    assert 'Source unavailable.' in fn_text  # non-github repo_meta -> no network fetch, clean fallback


def test_render_detail_panel_hides_callers_callees_when_edges_off():
    graph = _make_graph(
        nodes=[
            {'kind': 'module', 'name': 'mod', 'file': 'mod.py'},
            {'kind': 'function', 'name': 'mod.a', 'file': 'mod.py'},
            {'kind': 'function', 'name': 'mod.b', 'file': 'mod.py'},
        ],
        edges=[{'caller': 'mod.a', 'callee': 'mod.b', 'resolved': True}],
    )
    elements = build_elements(graph)

    shown = render_detail_panel('sym:mod.a', True, False, False, elements, _FAKE_REPO_META)
    hidden = render_detail_panel('sym:mod.a', False, False, False, elements, _FAKE_REPO_META)

    assert 'callees' in ' '.join(str(t) for t in _flatten_panel(shown))
    assert 'callees' not in ' '.join(str(t) for t in _flatten_panel(hidden))


def test_render_detail_panel_excludes_noise_side_callers_and_callees():
    graph = _make_graph(
        nodes=[
            {'kind': 'module', 'name': 'mod', 'file': 'mod.py'},
            {'kind': 'function', 'name': 'mod.real_func', 'file': 'mod.py'},
            {'kind': 'module', 'name': 'tests.test_mod', 'file': 'tests/test_mod.py', 'relative_path': 'tests/test_mod.py'},
            {'kind': 'function', 'name': 'tests.test_mod.test_real_func', 'file': 'tests/test_mod.py',
             'relative_path': 'tests/test_mod.py'},
        ],
        edges=[{'caller': 'tests.test_mod.test_real_func', 'callee': 'mod.real_func', 'resolved': True}],
    )
    elements = build_elements(graph)

    with_filter = render_detail_panel('sym:mod.real_func', True, True, False, elements, _FAKE_REPO_META)
    without_filter = render_detail_panel('sym:mod.real_func', True, False, False, elements, _FAKE_REPO_META)

    assert 'none resolved' in ' '.join(str(t) for t in _flatten_panel(with_filter))
    assert 'test_real_func' in ' '.join(str(t) for t in _flatten_panel(without_filter))


def _flatten_panel(sections):
    texts = []
    for section in sections:
        texts.extend(_render_text(section))
    return texts


# --- render_toast / render_breadcrumb ------------------------------------------

def test_render_toast_is_empty_with_no_selection_or_edges_off():
    graph = _make_graph([
        {'kind': 'module', 'name': 'mod', 'file': 'mod.py'},
        {'kind': 'function', 'name': 'mod.f', 'file': 'mod.py'},
    ])
    elements = build_elements(graph)

    assert render_toast(None, True, elements) == ''
    assert render_toast('sym:mod.f', False, elements) == ''


def test_render_toast_reports_total_call_relations():
    graph = _make_graph(
        nodes=[
            {'kind': 'module', 'name': 'mod', 'file': 'mod.py'},
            {'kind': 'function', 'name': 'mod.a', 'file': 'mod.py'},
            {'kind': 'function', 'name': 'mod.b', 'file': 'mod.py'},
            {'kind': 'function', 'name': 'mod.c', 'file': 'mod.py'},
        ],
        edges=[
            {'caller': 'mod.a', 'callee': 'mod.b', 'resolved': True},
            {'caller': 'mod.a', 'callee': 'mod.c', 'resolved': True},
        ],
    )
    elements = build_elements(graph)

    toast = render_toast('sym:mod.a', True, elements)
    assert '2' in _render_text(toast)


def test_render_breadcrumb_shows_the_selected_qualified_name():
    graph = _make_graph([{'kind': 'module', 'name': 'pkg.mod', 'file': 'pkg/mod.py'}])
    elements = build_elements(graph)

    assert render_breadcrumb('mod:pkg.mod', elements) == 'pkg.mod'
    assert render_breadcrumb(None, elements) == ''
