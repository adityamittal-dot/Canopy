import json
import re

import dash
from dash import dcc, html, Input, Output, State
from django.conf import settings
from django.templatetags.static import static
from django.urls import reverse
from django_plotly_dash import DjangoDash
from django_plotly_dash.dash_wrapper import PseudoFlask

from explorer.ai_chat import ask_about_repo, is_chat_enabled
from explorer.github_links import fetch_source_snippet, github_blob_url
from explorer.graph_data import (
  build_elements, callers_and_callees, index_children, subtree_node_count,
  noise_ids_for_tests, vendor_noise_ids,
)
from explorer.models import CommitAnalysis
from explorer.ratelimit import is_rate_limited

_original_pseudoflask_init = PseudoFlask.__init__


def _pseudoflask_init_with_secret_key(self):
  _original_pseudoflask_init(self)
  self.config['SECRET_KEY'] = settings.SECRET_KEY


PseudoFlask.__init__ = _pseudoflask_init_with_secret_key

app = DjangoDash('HelloCanopy')

app.layout = html.Div([
  html.H2('Canopy - Dash wiring check'),
  html.Button('Click me', id='hello-button', n_clicks=0),
  html.Div(id='hello-output'),
])

@app.callback(
  Output('hello-output','children'),
  Input('hello-button','n_clicks'),
)
def update_output(n_clicks):
  if not n_clicks:
    return 'Button not clicked yet.'
  return f'Button clicked {n_clicks} time(s) - Dash is alive inside Django.'


# ---------------------------------------------------------------------------
# RepoGraph: a nested-box explorer (repo -> packages -> modules -> classes ->
# functions), traced from a reference design. Packages/modules/classes are
# always rendered - only function-kind children are collapsed by default,
# per-container, via an explicit expand/collapse toggle. Two independent
# filters (tests, vendored deps) render their matching subtrees as dimmed
# "ghost" placeholders instead of omitting them silently.
# ---------------------------------------------------------------------------

graph_app = DjangoDash('RepoGraph', external_stylesheets=[static('explorer/canopy.css')])

# The AI chat panel is entirely optional and off by default - GEMINI_API_KEY
# is only ever set as a deliberate deploy-time choice, so checking it once at
# import time (rather than per-request) is correct: it can't change without a
# restart anyway. When disabled, none of the chat markup is even built -
# not hidden via CSS, just never constructed - so a disabled deployment
# carries zero chat-related payload or callback surface.
_CHAT_ENABLED = is_chat_enabled()

_CHAT_TOOLBAR_BUTTON = [
  html.Button('ai chat', id='toggle-chat', className='cy-toggle'),
] if _CHAT_ENABLED else []

_CHAT_STORES = [
  dcc.Store(id='chat-history-store', data=[]),
  dcc.Store(id='chat-open-store', data=False),
  # Whether the drawer is docked full-height along the right edge (a wider,
  # easier-to-read mode for an actual back-and-forth) instead of the small
  # floating card it starts as - toggled by the header's expand button.
  dcc.Store(id='chat-expanded-store', data=False),
  # Write-only target for the chat clientside callback below - a dedicated
  # store rather than reusing selection-sync-store, since Dash requires
  # allow_duplicate=True on *every* callback targeting a shared Output, and
  # this way the existing selection-highlight callback needs no changes.
  dcc.Store(id='chat-sync-store', data=None),
] if _CHAT_ENABLED else []

_CHAT_DRAWER = [
  html.Div(id='cy-chat', className='cy-chat', children=[
    html.Div(className='cy-chat__header', children=[
      html.Span('ask ai about this repo', className='cy-chat__title'),
      html.Div(className='cy-chat__header-actions', children=[
        html.Button('expand', id='chat-expand', className='cy-chat__expand'),
        html.Button('×', id='chat-close', className='cy-chat__close'),
      ]),
    ]),
    html.Div(id='cy-chat-messages', className='cy-chat__messages', children=[
      html.Div('Ask a question about this repo.', className='cy-chat__empty'),
    ]),
    html.Div(className='cy-chat__inputrow', children=[
      dcc.Input(
        id='chat-input', type='text', placeholder='ask about this repo…', debounce=False, n_submit=0,
        autoComplete='off', spellCheck=False,
      ),
      html.Button('send', id='chat-send', className='cy-chat__send'),
    ]),
  ]),
] if _CHAT_ENABLED else []

graph_app.layout = html.Div(className='cy-app', children=[
  dcc.Store(id='analysis-id-store', data=None),
  dcc.Store(id='elements-store', data=[]),
  dcc.Store(id='repo-meta-store', data={}),
  dcc.Store(id='expanded-store', data=[]),
  dcc.Store(id='selected-node-store', data=None),
  dcc.Store(id='show-edges-store', data=True),
  dcc.Store(id='hide-tests-store', data=True),
  dcc.Store(id='hide-vendor-store', data=True),
  # 'tree' (nested containment boxes) or 'graph' (top-down org-chart with
  # connector lines) - same underlying elements/expanded/selection state,
  # just two different renderers for it (see render_tree below).
  dcc.Store(id='view-mode-store', data='tree'),
  # Current zoom level as a percentage (100 = actual size). Purely a
  # presentation concern - never touches elements/expanded/selection - so
  # it's read and written entirely clientside (see the zoom callbacks
  # below), same no-server-round-trip reasoning as selection highlighting.
  dcc.Store(id='zoom-level-store', data=100),
  # Write-only target for the clientside selection-highlight callback below
  # (a clientside_callback needs some Output to write to, even though
  # nothing ever reads this one back).
  dcc.Store(id='selection-sync-store', data=None),
  # Same write-only pattern, for the clientside callback that applies the
  # zoom transform.
  dcc.Store(id='zoom-sync-store', data=None),
  *_CHAT_STORES,

  html.Div(className='cy-shell', children=[
    html.Div(id='cy-header'),
    html.Div(className='cy-toolbar', children=[
      html.Div(className='cy-search', children=[
        html.Span('search', className='cy-search__label'),
        html.Div(className='cy-search__box', children=[
          html.Span('/', className='cy-search__prefix'),
          dcc.Input(
            id='search-input', type='text', placeholder='name or path', debounce=False, n_submit=0,
            autoComplete='off', spellCheck=False,
          ),
        ]),
      ]),
      html.Span(className='cy-vdivider'),
      html.Button('view: tree', id='toggle-view-mode', className='cy-toggle'),
      # Zoom is a tree-view-only option (the grid already reflows to fit,
      # and the org-chart view is meant to always render at its natural
      # size, same as before zoom existed) - hidden outright rather than
      # just disabled when view-mode-store is 'graph' (see
      # render_zoom_control_visibility below). Grouped with its own
      # divider so hiding it doesn't leave two adjacent dividers behind.
      html.Div(id='cy-zoom-control-group', className='cy-zoom-control-group', children=[
        html.Div(className='cy-zoomctl', children=[
          html.Button('−', id='zoom-out', className='cy-zoomctl__btn', title='Zoom out', **{'aria-label': 'Zoom out'}),
          html.Button('100%', id='zoom-reset', className='cy-zoomctl__pct', title='Reset zoom to 100%'),
          html.Button('+', id='zoom-in', className='cy-zoomctl__btn', title='Zoom in', **{'aria-label': 'Zoom in'}),
          html.Button('fit', id='zoom-fit', className='cy-zoomctl__btn cy-zoomctl__btn--fit', title='Zoom to fit the whole graph'),
        ]),
        html.Span(className='cy-vdivider'),
      ]),
      html.Button('edges: on', id='toggle-edges', className='cy-toggle cy-toggle--active'),
      html.Button('tests: hide', id='toggle-tests', className='cy-toggle cy-toggle--active'),
      html.Button('vendor: hide', id='toggle-vendor', className='cy-toggle cy-toggle--active'),
      *_CHAT_TOOLBAR_BUTTON,
      html.Div(id='cy-breadcrumb', className='cy-breadcrumb'),
    ]),
    html.Div(className='cy-body', children=[
      html.Div(className='cy-main', children=[
        html.Div(className='cy-canvas', children=[
          html.Div(id='cy-tag', className='cy-canvas__tag'),
          # cy-zoom-scaler is sized (inline, by the clientside apply_zoom
          # callback below) to the tree's natural size times the current
          # zoom level - that's what actually shrinks/grows the scrollable
          # footprint .cy-canvas's own overflow:auto reacts to. cy-tree
          # itself is absolutely positioned inside it and just gets a CSS
          # transform: scale(), which only repaints pixels and never
          # affects layout on its own.
          html.Div(id='cy-zoom-scaler', className='cy-zoom-scaler', children=[
            html.Div(id='cy-tree', className='cy-zoom-content'),
          ]),
          html.Div(className='cy-canvas__footer', children=[
            html.Div(className='cy-legend', children=[
              html.Div([html.Span(className='cy-dot', style={'background': 'var(--cy-repo)'}), html.Span('repo')], className='cy-legend__item'),
              html.Div([html.Span(className='cy-dot', style={'background': 'var(--cy-pkg)'}), html.Span('package')], className='cy-legend__item'),
              html.Div([html.Span(className='cy-dot', style={'background': 'var(--cy-mod)'}), html.Span('module')], className='cy-legend__item'),
              html.Div([html.Span(className='cy-dot', style={'background': 'var(--cy-cls)'}), html.Span('class')], className='cy-legend__item'),
              html.Div([html.Span(className='cy-dot', style={'background': 'var(--cy-fn)'}), html.Span('function')], className='cy-legend__item'),
            ]),
            html.Div(id='cy-toast'),
          ]),
        ]),
      ]),
      html.Aside(id='cy-panel', className='cy-panel'),
    ]),
    *_CHAT_DRAWER,
  ]),
])


# --- data loading -----------------------------------------------------------

@graph_app.callback(
  Output('elements-store', 'data'),
  Output('repo-meta-store', 'data'),
  Input('analysis-id-store', 'data'),
)
def load_elements(analysis_id):
  if not analysis_id:
    return [], {}

  try:
    analysis = CommitAnalysis.objects.select_related('repo').get(pk=analysis_id)
  except CommitAnalysis.DoesNotExist:
    return [], {}

  elements = build_elements(analysis.graph, repo_label=analysis.repo.name)
  repo_meta = {
    'url': analysis.repo.url,
    'name': analysis.repo.name,
    'commit_hash': analysis.commit_hash,
  }
  return elements, repo_meta


# --- header / tag / toggles --------------------------------------------------

@graph_app.callback(
  Output('cy-header', 'children'),
  Output('cy-tag', 'children'),
  Input('elements-store', 'data'),
  Input('repo-meta-store', 'data'),
)
def render_header(elements, repo_meta):
  node_count = sum(1 for el in elements if el['data'].get('kind') not in (None, 'call'))
  edge_count = sum(1 for el in elements if el['data'].get('kind') == 'call')

  header = html.Div(className='cy-header', children=[
    html.A(href=reverse('analyze'), className='cy-header__logo', children=[
      html.Span(className='cy-header__logo-dot'),
      html.Span('canopy', className='cy-header__wordmark'),
      html.Span('/ survey', className='cy-header__subpath'),
    ]),
    html.Div(className='cy-header__meta', children=(
      [
        html.Span('repo', className='muted'),
        html.Span(repo_meta.get('name', ''), className='fg'),
        html.Span('@', className='faint'),
        html.Span(repo_meta.get('commit_hash', '')[:7], className='accent'),
        html.Span(className='cy-vdivider'),
        html.Span(f'{node_count} nodes', className='muted'),
        html.Span('·', className='faint'),
        html.Span(f'{edge_count} edges', className='muted'),
      ] if repo_meta.get('name') else []
    )),
    html.A(
      html.Span(className='cy-header__github-icon'),
      href='https://github.com/adityamittal-dot/Canopy',
      target='_blank',
      rel='noreferrer',
      title='View source on GitHub',
      className='cy-header__github',
    ),
  ])

  tag = f"repo · {repo_meta['name'].upper()}" if repo_meta.get('name') else ''
  return header, tag


def _make_toggle_callback(button_id, store_id):
  @graph_app.callback(
    Output(store_id, 'data'),
    Input(button_id, 'n_clicks'),
    State(store_id, 'data'),
    prevent_initial_call=True,
  )
  def _toggle(_n_clicks, current):
    return not current
  return _toggle


_make_toggle_callback('toggle-edges', 'show-edges-store')
_make_toggle_callback('toggle-tests', 'hide-tests-store')
_make_toggle_callback('toggle-vendor', 'hide-vendor-store')


@graph_app.callback(
  Output('view-mode-store', 'data'),
  Input('toggle-view-mode', 'n_clicks'),
  State('view-mode-store', 'data'),
  prevent_initial_call=True,
)
def toggle_view_mode(_n_clicks, current):
  return 'graph' if current == 'tree' else 'tree'


@graph_app.callback(
  Output('toggle-view-mode', 'children'),
  Input('view-mode-store', 'data'),
)
def render_view_mode_toggle(view_mode):
  return 'view: graph' if view_mode == 'graph' else 'view: tree'


@graph_app.callback(
  Output('cy-zoom-control-group', 'style'),
  Input('view-mode-store', 'data'),
)
def render_zoom_control_visibility(view_mode):
  return {'display': 'none'} if view_mode == 'graph' else {}


# Entirely clientside - the button-click -> new zoom % logic never needs
# elements/expanded/selection, so there's no reason to pay for a server
# round trip on every zoom click (same reasoning as the selection-highlight
# clientside callback further down). django-plotly-dash's clientside
# dispatch doesn't confirm support for dash_clientside.callback_context (its
# server-side CallbackContext shim is known to be missing pieces - see
# _parse_triggered above), so which button fired is tracked by hand instead:
# a closure comparing each call's n_clicks against what it saw last time.
graph_app.clientside_callback(
  """
  function(nIn, nOut, nReset, nFit, currentZoom) {
    // MIN is a floor for manual +/- stepping only, chosen so each step stays
    // usable - "fit" has its own, much lower floor (FIT_MIN) because its
    // whole job is showing the entire graph even when that legitimately
    // needs a smaller scale than manual zooming should ever land on.
    var MIN = 20, MAX = 200, STEP = 20, FIT_MIN = 5;
    var prev = window._cyZoomClicks || {inN: 0, outN: 0, resetN: 0, fitN: 0};
    var zoom = currentZoom || 100;
    var changed = true;

    if ((nIn || 0) > prev.inN) {
      zoom = Math.min(MAX, zoom + STEP);
    } else if ((nOut || 0) > prev.outN) {
      zoom = Math.max(MIN, zoom - STEP);
    } else if ((nReset || 0) > prev.resetN) {
      zoom = 100;
    } else if ((nFit || 0) > prev.fitN) {
      var viewport = document.querySelector('.cy-canvas');
      var content = document.getElementById('cy-tree');
      if (viewport && content) {
        // Compact mode (see canopy.css) hides text and shrinks the tree's
        // own natural size - measuring while it's active would fit against
        // that collapsed layout instead of the real one, so it's lifted
        // for the measurement and left for the apply-zoom callback (which
        // runs right after, off the zoom value returned below) to redecide.
        var wasCompact = content.classList.contains('cy-zoom-compact');
        if (wasCompact) { content.classList.remove('cy-zoom-compact'); }
        if (content.scrollWidth) {
          // clientWidth includes the canvas's own left/right padding, which
          // isn't available for content - subtract it, or "fit" leaves a
          // residual horizontal scrollbar exactly padding-wide.
          var style = window.getComputedStyle(viewport);
          var availWidth = viewport.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
          var fitScale = Math.min(availWidth / content.scrollWidth, 1);
          zoom = Math.min(MAX, Math.max(FIT_MIN, Math.floor(fitScale * 100)));
        }
        if (wasCompact) { content.classList.add('cy-zoom-compact'); }
      }
    } else {
      changed = false;
    }

    window._cyZoomClicks = {inN: nIn || 0, outN: nOut || 0, resetN: nReset || 0, fitN: nFit || 0};
    return changed ? zoom : window.dash_clientside.no_update;
  }
  """,
  Output('zoom-level-store', 'data'),
  Input('zoom-in', 'n_clicks'),
  Input('zoom-out', 'n_clicks'),
  Input('zoom-reset', 'n_clicks'),
  Input('zoom-fit', 'n_clicks'),
  State('zoom-level-store', 'data'),
  prevent_initial_call=True,
)


@graph_app.callback(
  Output('zoom-reset', 'children'),
  Input('zoom-level-store', 'data'),
)
def render_zoom_label(zoom_pct):
  return f'{zoom_pct}%'


# Applies the actual zoom: sizes cy-zoom-scaler to the tree's natural size
# times the zoom level (that's what .cy-canvas's overflow:auto scrolls
# against) and scales cy-tree itself to match. Re-runs whenever the tree's
# content changes too (not just the zoom level) since expand/collapse,
# filtering, or loading a new repo all change the natural size a given zoom
# % now maps to. Below 50%, text has shrunk past the point of being legible
# rather than blurry, so cy-zoom-compact (see canopy.css) swaps it out for
# plain color-coded blocks - the boxes' kind-color border/dot plus a native
# title tooltip on hover, same info without rendering illegible glyphs.
#
# Zoom is tree-view only (see render_zoom_control_visibility above) - the
# org-chart view always renders at its natural size, same as before zoom
# existed, regardless of whatever zoom-level-store is currently holding
# for the tree view.
graph_app.clientside_callback(
  """
  function(zoomPct, viewMode, _treeChildren) {
    var zoom = viewMode === 'graph' ? 1 : (zoomPct || 100) / 100;
    var scaler = document.getElementById('cy-zoom-scaler');
    var content = document.getElementById('cy-tree');
    if (scaler && content) {
      // Compact mode changes the tree's natural (untransformed) size, so
      // it has to be toggled *before* scrollWidth/scrollHeight are read
      // below - otherwise a zoom change that also crosses the compact
      // threshold measures against the stale, pre-toggle layout.
      content.classList.toggle('cy-zoom-compact', zoom <= 0.5);
      content.style.transform = 'scale(' + zoom + ')';
      scaler.style.width = (content.scrollWidth * zoom) + 'px';
      scaler.style.height = (content.scrollHeight * zoom) + 'px';
    }
    return window.dash_clientside.no_update;
  }
  """,
  Output('zoom-sync-store', 'data'),
  Input('zoom-level-store', 'data'),
  Input('view-mode-store', 'data'),
  Input('cy-tree', 'children'),
)


@graph_app.callback(
  Output('toggle-edges', 'children'),
  Output('toggle-edges', 'className'),
  Input('show-edges-store', 'data'),
)
def render_edges_toggle(show_edges):
  label = 'edges: on' if show_edges else 'edges: off'
  className = 'cy-toggle cy-toggle--active' if show_edges else 'cy-toggle'
  return label, className


def _render_filter_toggle(hidden, verb):
  label = f'{verb}: hide' if hidden else f'{verb}: show'
  className = 'cy-toggle cy-toggle--active' if hidden else 'cy-toggle'
  return label, className


@graph_app.callback(
  Output('toggle-tests', 'children'),
  Output('toggle-tests', 'className'),
  Input('hide-tests-store', 'data'),
)
def render_tests_toggle(hide_tests):
  return _render_filter_toggle(hide_tests, 'tests')


@graph_app.callback(
  Output('toggle-vendor', 'children'),
  Output('toggle-vendor', 'className'),
  Input('hide-vendor-store', 'data'),
)
def render_vendor_toggle(hide_vendor):
  return _render_filter_toggle(hide_vendor, 'vendor')


# --- interaction: select / expand / navigate / search ------------------------

def _find_element(elements, node_id):
  return next((el for el in elements if el['data']['id'] == node_id), None)


def _resolve_search_target(query, elements, excluded_ids):
  """Case-insensitive substring match against label and qualified name,
  restricted to module/class/function nodes. Excludes noise-filtered ids -
  a match there wouldn't actually be visible even after reveal, since
  noise-hiding is unconditional (see render_tree). Prefers an exact label
  match, else the shortest qualified name among substring matches."""
  query = (query or '').strip()
  if not query:
    return None

  query_lower = query.lower()
  candidates = [
    el for el in elements
    if el['data'].get('kind') in ('module', 'class', 'function')
    and el['data']['id'] not in excluded_ids
    and (query_lower in el['data']['label'].lower() or query_lower in el['data'].get('name', '').lower())
  ]
  if not candidates:
    return None

  exact = [el for el in candidates if el['data']['label'].lower() == query_lower]
  best = exact[0] if exact else min(candidates, key=lambda el: len(el['data'].get('name') or el['data']['label']))
  return best['data']['id']


def _reveal_target(target_id, expanded, elements):
  """Only a function target ever needs revealing - packages/modules/classes
  are always rendered (see render_tree), so the only thing that can hide a
  target is its own immediate parent's function list being collapsed.
  Returns the updated expanded list, or None if nothing needs to change."""
  target = _find_element(elements, target_id)
  if target is None or target['data']['kind'] != 'function':
    return None
  parent_id = target['data'].get('parent')
  if parent_id is None or parent_id in expanded:
    return None
  return expanded + [parent_id]


def _toggle_membership(items, item_id):
  """Add item_id if absent, remove if present. Always returns a new list."""
  if item_id in items:
    return [i for i in items if i != item_id]
  return items + [item_id]


def _resolve_click(action, node_id, expanded, elements, currently_selected):
  """Pure decision logic for one already-identified click action. Returns
  (new_expanded_or_None, new_selected_or_None) - None means "no change",
  which the calling callback translates to dash.no_update. Kept separate
  from the callback itself (which needs a live dash.callback_context) so
  this can be unit-tested directly."""
  if action == 'expand':
    return _toggle_membership(expanded, node_id), None

  if action in ('select', 'navigate'):
    if node_id == currently_selected:
      return None, None
    new_expanded = _reveal_target(node_id, expanded, elements) if action == 'navigate' else None
    return new_expanded, node_id

  return None, None


def _resolve_search(search_query, elements, expanded, currently_selected, hide_tests, hide_vendor):
  """Same (new_expanded_or_None, new_selected_or_None) convention as
  _resolve_click, for a search submission."""
  excluded = set()
  if hide_tests:
    excluded |= noise_ids_for_tests(elements)
  if hide_vendor:
    excluded |= vendor_noise_ids(elements)

  target_id = _resolve_search_target(search_query, elements, excluded)
  if target_id is None or target_id == currently_selected:
    return None, None
  return _reveal_target(target_id, expanded, elements), target_id


def _parse_triggered(triggered):
  """django-plotly-dash's CallbackContext shim doesn't implement Dash's
  `triggered_id` convenience property (confirmed via a live click - it
  raises AttributeError, not just an outdated stub) - only `.triggered`,
  a list of {'prop_id': 'id.prop', 'value': ...} dicts. Parse the
  component id out of prop_id by hand instead: strip the trailing
  '.prop_name', then JSON-decode what's left if it looks like a
  pattern-matching dict id. Returns (triggered_id, value), or (None, None)
  if nothing triggered."""
  if not triggered:
    return None, None
  prop_id = triggered[0]['prop_id']
  component_id_str = prop_id.rsplit('.', 1)[0]
  triggered_id = json.loads(component_id_str) if component_id_str.startswith('{') else component_id_str
  return triggered_id, triggered[0]['value']


@graph_app.callback(
  Output('expanded-store', 'data'),
  Output('selected-node-store', 'data'),
  Input({'type': 'cy-click', 'action': dash.ALL, 'id': dash.ALL}, 'n_clicks'),
  Input('search-input', 'n_submit'),
  State('search-input', 'value'),
  State('expanded-store', 'data'),
  State('elements-store', 'data'),
  State('selected-node-store', 'data'),
  State('hide-tests-store', 'data'),
  State('hide-vendor-store', 'data'),
  prevent_initial_call=True,
)
def handle_interaction(_click_values, _n_submit, search_query, expanded, elements,
                        currently_selected, hide_tests, hide_vendor):
  triggered_id, triggered_value = _parse_triggered(dash.callback_context.triggered)

  if triggered_id == 'search-input':
    new_expanded, new_selected = _resolve_search(search_query, elements, expanded, currently_selected, hide_tests, hide_vendor)
  elif isinstance(triggered_id, dict) and triggered_id.get('type') == 'cy-click' and triggered_id.get('action') == 'clear' and triggered_value:
    # The detail panel's close button (mobile: it's a full-screen drawer, so
    # it needs an explicit way back out) - deselects outright, which the
    # (new_selected is not None -> dash.no_update) convention below can't
    # express, so this bypasses it and returns straight away.
    return dash.no_update, None
  elif isinstance(triggered_id, dict) and triggered_id.get('type') == 'cy-click' and triggered_value:
    # A pattern-matching ALL input re-fires not only on a real click but
    # also whenever the *set* of matched components changes (e.g.
    # re-rendering the tree after an expand/collapse mounts a fresh batch
    # of buttons) - a freshly-mounted (never clicked) component's n_clicks
    # is still 0 in that case, which the `and triggered_value` above excludes.
    new_expanded, new_selected = _resolve_click(triggered_id.get('action'), triggered_id.get('id'), expanded, elements, currently_selected)
  else:
    new_expanded, new_selected = None, None

  return (
    new_expanded if new_expanded is not None else dash.no_update,
    new_selected if new_selected is not None else dash.no_update,
  )


# --- tree rendering -----------------------------------------------------------

def _click_id(action, node_id):
  return {'type': 'cy-click', 'action': action, 'id': node_id}


def _fn_pill(data, selected_id):
  node_id = data['id']
  className = 'cy-fn-pill' + (' is-selected' if node_id == selected_id else '')
  return html.Button(
    data['label'], id=_click_id('select', node_id), className=className, title=data.get('name', data['label']),
    **{'data-node-id': node_id},
  )


def _ghost_box(data, category, elements):
  count = subtree_node_count(elements, data['id'])
  noun = 'node' if count == 1 else 'nodes'
  return html.Div(className='cy-ghost', children=[
    html.Div(className='cy-ghost__label', children=[
      html.Span(className='cy-dot cy-dot--hollow'),
      html.Span(f"{data['kind']} / {data['label']}"),
    ]),
    html.Div(f'filtered · {category} ({count} {noun})', className='cy-ghost__status'),
  ])


def _partition_children(children, test_noise, vendor_noise):
  """Split a container's direct children into (containers, functions,
  ghosts) - ghosts being (data, category) pairs for noise-filtered children,
  rendered as dimmed placeholders rather than omitted. Shared by every level
  of the tree, including the top-level repo children in render_tree, so a
  filtered item is never silently dropped no matter how deep it is."""
  containers, functions, ghosts = [], [], []
  for child in children:
    cid = child['data']['id']
    if cid in test_noise:
      ghosts.append((child['data'], 'test'))
    elif cid in vendor_noise:
      ghosts.append((child['data'], 'vendor'))
    elif child['data']['kind'] == 'function':
      functions.append(child)
    else:
      containers.append(child)
  return containers, functions, ghosts


def _render_container(node_id, elements, children_index, expanded, test_noise, vendor_noise, selected_id):
  node = _find_element(elements, node_id)
  data = node['data']
  kind = data['kind']
  children = children_index.get(node_id, [])
  container_children, function_children, ghosts = _partition_children(children, test_noise, vendor_noise)

  body = [
    _render_container(child['data']['id'], elements, children_index, expanded, test_noise, vendor_noise, selected_id)
    for child in container_children
  ]

  if function_children:
    if node_id in expanded:
      body.append(html.Div(
        [_fn_pill(f['data'], selected_id) for f in function_children],
        className='cy-fn-list',
      ))
    else:
      n = len(function_children)
      body.append(html.Div(f"collapsed · click to expand ({n} fn{'s' if n != 1 else ''})", className='cy-box__status'))

  for ghost_data, category in ghosts:
    body.append(_ghost_box(ghost_data, category, elements))

  label_className = 'cy-box__label' + (' is-selected' if node_id == selected_id else '')
  header_children = [
    html.Button([
      html.Span(className='cy-dot'),
      html.Span(f"{kind} / {data['label']}", className='name'),
    ], id=_click_id('select', node_id), className=label_className, title=data.get('name', data['label']), **{'data-node-id': node_id}),
  ]
  if function_children:
    header_children.append(html.Button(
      '−' if node_id in expanded else '+',
      id=_click_id('expand', node_id),
      className='cy-box__expand',
    ))

  box_className = f'cy-box cy-box--{kind}' + (' is-selected' if node_id == selected_id else '')
  box_body = [html.Div(header_children, className='cy-box__header')]
  if body:
    box_body.append(html.Div(body, className='cy-box__children'))

  return html.Div(box_body, className=box_className)


def _repo_link_label(repo_meta):
  """The repo root's header: a GitHub link when a repo URL is known,
  otherwise a plain label - same content either way, just linkified."""
  repo_meta = repo_meta or {}
  name = repo_meta.get('name') or 'repo'
  content = [
    html.Span(className='cy-dot', style={'background': 'var(--cy-repo)'}),
    html.Span(f'repo / {name}', className='name'),
  ]
  url = repo_meta.get('url')
  if url:
    return html.A(content, href=url, target='_blank', rel='noreferrer', className='cy-box__label cy-k-repo', title=name)
  return html.Div(content, className='cy-box__label cy-k-repo', title=name)


@graph_app.callback(
  Output('cy-tree', 'children'),
  Input('elements-store', 'data'),
  Input('expanded-store', 'data'),
  Input('hide-tests-store', 'data'),
  Input('hide-vendor-store', 'data'),
  Input('view-mode-store', 'data'),
  Input('repo-meta-store', 'data'),
  # State, not Input: selecting a node is by far the most frequent
  # interaction, and doesn't change which boxes/pills exist - only which
  # one is highlighted. Re-rendering and re-serializing the *entire* tree
  # (hundreds of KB for a mid-size repo) on every single click would make
  # every click pay for a full-tree round-trip. A clientside callback
  # (see the clientside_callback below) handles highlighting instantly in
  # the browser instead; this State is only here so a structural
  # re-render (expand/collapse, filter toggle) still bakes in whichever
  # node is currently selected.
  State('selected-node-store', 'data'),
)
def render_tree(elements, expanded, hide_tests, hide_vendor, view_mode='tree', repo_meta=None, selected_id=None):
  if not elements:
    return html.Div('No analysis loaded.', className='cy-box__status')

  test_noise = noise_ids_for_tests(elements) if hide_tests else set()
  vendor_noise = vendor_noise_ids(elements) if hide_vendor else set()
  children_index = index_children(elements)
  top_level = children_index.get('repo', [])
  containers, _functions, ghosts = _partition_children(top_level, test_noise, vendor_noise)
  # _functions is always empty in practice - a function always nests under a
  # module or class, never directly under the repo - but _partition_children
  # handles every level uniformly regardless, so nothing special-cases that.

  if view_mode == 'graph':
    return _render_orgchart(containers, ghosts, elements, children_index, expanded, test_noise, vendor_noise, selected_id, repo_meta)

  boxes = [
    _render_container(child['data']['id'], elements, children_index, expanded, test_noise, vendor_noise, selected_id)
    for child in containers
  ]
  boxes.extend(_ghost_box(ghost_data, category, elements) for ghost_data, category in ghosts)
  return html.Div([
    html.Div([_repo_link_label(repo_meta)], className='cy-box__header'),
    html.Div(boxes, className='cy-grid', style={'marginTop': '.75rem'}),
  ], className='cy-box cy-box--repo cy-box--root')


# --- org-chart view: same elements/expanded/selection state as the nested-
# box tree above, rendered instead as a top-down hierarchy connected by
# lines (classic CSS org-chart via nested <ul>/<li> lists), so switching
# view modes never changes what's expanded or selected. ------------------

def _orgchart_status(node_id, function_children, expanded, selected_id):
  n = len(function_children)
  if node_id in expanded:
    return html.Div([_fn_pill(f['data'], selected_id) for f in function_children], className='cy-fn-list')
  return html.Div(f"collapsed · click to expand ({n} fn{'s' if n != 1 else ''})", className='cy-box__status')


def _orgchart_node_box(node_id, elements, children_index, expanded, test_noise, vendor_noise, selected_id):
  node = _find_element(elements, node_id)
  data = node['data']
  kind = data['kind']
  function_children = [
    child for child in children_index.get(node_id, [])
    if child['data']['kind'] == 'function'
    and child['data']['id'] not in test_noise
    and child['data']['id'] not in vendor_noise
  ]

  label_className = 'cy-box__label' + (' is-selected' if node_id == selected_id else '')
  header_children = [
    html.Button([
      html.Span(className='cy-dot'),
      html.Span(f"{kind} / {data['label']}", className='name'),
    ], id=_click_id('select', node_id), className=label_className, title=data.get('name', data['label']), **{'data-node-id': node_id}),
  ]
  if function_children:
    header_children.append(html.Button(
      '−' if node_id in expanded else '+',
      id=_click_id('expand', node_id),
      className='cy-box__expand',
    ))

  box_className = f'cy-box cy-box--{kind} cy-og-node' + (' is-selected' if node_id == selected_id else '')
  box_body = [html.Div(header_children, className='cy-box__header')]
  if function_children:
    box_body.append(_orgchart_status(node_id, function_children, expanded, selected_id))
  return html.Div(box_body, className=box_className)


def _orgchart_ghost_li(ghost_data, category, elements):
  return html.Li(_ghost_box(ghost_data, category, elements))


def _orgchart_li(node_id, elements, children_index, expanded, test_noise, vendor_noise, selected_id):
  node_box = _orgchart_node_box(node_id, elements, children_index, expanded, test_noise, vendor_noise, selected_id)
  containers, _functions, ghosts = _partition_children(children_index.get(node_id, []), test_noise, vendor_noise)

  li_children = [node_box]
  child_items = [
    _orgchart_li(child['data']['id'], elements, children_index, expanded, test_noise, vendor_noise, selected_id)
    for child in containers
  ]
  child_items.extend(_orgchart_ghost_li(ghost_data, category, elements) for ghost_data, category in ghosts)
  if child_items:
    li_children.append(html.Ul(child_items))
  return html.Li(li_children)


def _render_orgchart(containers, ghosts, elements, children_index, expanded, test_noise, vendor_noise, selected_id, repo_meta):
  repo_box = html.Div([
    html.Div([_repo_link_label(repo_meta)], className='cy-box__header'),
  ], className='cy-box cy-box--repo cy-og-node')

  child_items = [
    _orgchart_li(child['data']['id'], elements, children_index, expanded, test_noise, vendor_noise, selected_id)
    for child in containers
  ]
  child_items.extend(_orgchart_ghost_li(ghost_data, category, elements) for ghost_data, category in ghosts)

  root_children = [repo_box]
  if child_items:
    root_children.append(html.Ul(child_items))

  return html.Div(html.Ul(html.Li(root_children)), className='cy-orgchart')


# Runs entirely in the browser, no server round-trip: clears whichever
# box/pill was previously highlighted and highlights the one matching
# selected-node-store, by looking up the plain `data-node-id` attribute
# rather than parsing Dash's own pattern-matching id encoding.
graph_app.clientside_callback(
  """
  function(selectedId) {
    document.querySelectorAll('.cy-box.is-selected, .cy-box__label.is-selected, .cy-fn-pill.is-selected')
      .forEach(function(el) { el.classList.remove('is-selected'); });

    if (selectedId) {
      var escaped = CSS.escape(String(selectedId));
      var label = document.querySelector('.cy-box__label[data-node-id="' + escaped + '"]');
      if (label) {
        label.classList.add('is-selected');
        var box = label.closest('.cy-box');
        if (box) { box.classList.add('is-selected'); }
        label.scrollIntoView({behavior: 'smooth', block: 'center', inline: 'nearest'});
      }
      var pill = document.querySelector('.cy-fn-pill[data-node-id="' + escaped + '"]');
      if (pill) {
        pill.classList.add('is-selected');
        pill.scrollIntoView({behavior: 'smooth', block: 'center', inline: 'nearest'});
      }
    }

    return window.dash_clientside.no_update;
  }
  """,
  Output('selection-sync-store', 'data'),
  Input('selected-node-store', 'data'),
)


# --- breadcrumb + toast --------------------------------------------------------

@graph_app.callback(
  Output('cy-breadcrumb', 'children'),
  Input('selected-node-store', 'data'),
  State('elements-store', 'data'),
)
def render_breadcrumb(selected_id, elements):
  if not selected_id:
    return ''
  el = _find_element(elements, selected_id)
  if el is None:
    return ''
  return el['data'].get('name', el['data']['label'])


@graph_app.callback(
  Output('cy-toast', 'children'),
  Input('selected-node-store', 'data'),
  Input('show-edges-store', 'data'),
  State('elements-store', 'data'),
)
def render_toast(selected_id, show_edges, elements):
  if not selected_id or not show_edges:
    return ''
  el = _find_element(elements, selected_id)
  if el is None:
    return ''
  callers, callees = callers_and_callees(elements, selected_id)
  total = len(callers) + len(callees)
  return html.Div(className='cy-toast', children=[
    html.Span(str(total), className='accent'),
    f' call relation{"s" if total != 1 else ""} highlighted for ',
    html.Span(el['data']['label'], className='fg'),
  ])


# --- detail panel --------------------------------------------------------------

_KEYWORD_RE = re.compile(r'^(\s*)(async def|def|class)\b(.*)$')


def _highlight_line(line):
  match = _KEYWORD_RE.match(line)
  if match:
    indent, keyword, rest = match.groups()
    return [indent, html.Span(keyword, className='cy-source__kw'), rest]
  if line.strip().startswith(('"""', "'''")):
    return [html.Span(line, className='cy-source__doc')]
  return [line]


def _render_source_block(snippet, start_lineno):
  lines = snippet.split('\n')
  rows = []
  for offset, line in enumerate(lines):
    rows.append(html.Div([
      html.Span(str(start_lineno + offset), className='cy-source__lineno'),
      html.Span(_highlight_line(line)),
    ], className='cy-source__line'))
  return html.Div(rows, className='cy-source')


@graph_app.callback(
  Output('cy-panel', 'children'),
  Input('selected-node-store', 'data'),
  Input('show-edges-store', 'data'),
  Input('hide-tests-store', 'data'),
  Input('hide-vendor-store', 'data'),
  State('elements-store', 'data'),
  State('repo-meta-store', 'data'),
)
def render_detail_panel(selected_id, show_edges, hide_tests, hide_vendor, elements, repo_meta):
  if not selected_id:
    return html.Div('Select a node to see its details.', className='cy-panel__section')

  el = _find_element(elements, selected_id)
  if el is None:
    return dash.no_update

  data = el['data']
  sections = [
    html.Div(className='cy-panel__header', children=[
      html.Span('node detail', className='cy-panel__label'),
      html.Div(className='cy-panel__header-right', children=[
        html.Span(data['kind'], className=f"cy-k-{data['kind']}"),
        html.Button(
          '×', id=_click_id('clear', 'panel'), className='cy-panel__close',
          **{'aria-label': 'Close panel'},
        ),
      ]),
    ]),
  ]

  info_block = [html.Div(data.get('name', data['label']), className='cy-panel__name')]
  if data.get('docstring'):
    info_block.append(html.Div(data['docstring'], className='cy-panel__doc'))
  if data.get('relative_path'):
    info_block.append(html.Div(data['relative_path'], className='cy-panel__path'))
    if data.get('lineno'):
      line_text = f"L{data['lineno']}" + (f"–{data['end_lineno']}" if data.get('end_lineno') else '')
      info_block.append(html.Div(line_text, className='cy-panel__lines'))
    repo_url = repo_meta.get('url') if repo_meta else None
    if repo_url:
      blob_url = github_blob_url(repo_url, repo_meta['commit_hash'], data['relative_path'], data.get('lineno'), data.get('end_lineno'))
      if blob_url:
        info_block.append(html.A('view on GitHub →', href=blob_url, target='_blank', rel='noreferrer', className='cy-panel__link'))
  sections.append(html.Div(info_block, className='cy-panel__section'))

  if data['kind'] == 'function':
    sections.append(html.Div(className='cy-stats', children=[
      html.Div([html.Div(str(data.get('loc', 0)), className='cy-stat__value'), html.Div('loc', className='cy-stat__label')]),
      html.Div([html.Div(str(data.get('complexity', 0)), className='cy-stat__value'), html.Div('ccyc', className='cy-stat__label')]),
      html.Div([html.Div(str(data.get('fan_in', 0)), className='cy-stat__value'), html.Div('fan-in', className='cy-stat__label')]),
      html.Div([html.Div(str(data.get('fan_out', 0)), className='cy-stat__value'), html.Div('fan-out', className='cy-stat__label')]),
    ]))

    repo_url = repo_meta.get('url') if repo_meta else None
    if repo_url and data.get('relative_path'):
      snippet = fetch_source_snippet(
        repo_url, repo_meta['commit_hash'], data['relative_path'], data.get('lineno'), data.get('end_lineno'),
      )
      source_body = _render_source_block(snippet, data.get('lineno', 1)) if snippet is not None else html.Div(
        'Source unavailable.', className='cy-panel__doc',
      )
      sections.append(html.Div([
        html.Div('source', className='cy-panel__label', style={'marginBottom': '.5rem'}),
        source_body,
      ], className='cy-panel__section'))

  if show_edges:
    excluded = set()
    if hide_tests:
      excluded |= noise_ids_for_tests(elements)
    if hide_vendor:
      excluded |= vendor_noise_ids(elements)

    callers, callees = callers_and_callees(elements, selected_id)
    callers = [c for c in callers if c not in excluded]
    callees = [c for c in callees if c not in excluded]

    def nav_button(node_id):
      target = _find_element(elements, node_id)
      label = target['data'].get('name', target['data']['label']) if target else node_id
      return html.Button(label, id=_click_id('navigate', node_id), className='cy-list-btn')

    sections.append(html.Div([
      html.Div(['callers ', html.Span(f'· {len(callers)}', className='cy-k-repo')], className='cy-panel__label', style={'marginBottom': '.5rem'}),
      html.Div([nav_button(c) for c in callers] or [html.Div('none resolved', className='cy-panel__doc')]),
    ], className='cy-panel__section'))

    sections.append(html.Div([
      html.Div(['callees ', html.Span(f'· {len(callees)}', className='cy-k-repo')], className='cy-panel__label', style={'marginBottom': '.5rem'}),
      html.Div([nav_button(c) for c in callees] or [html.Div('none resolved', className='cy-panel__doc')]),
    ], className='cy-panel__section', style={'borderBottom': 'none'}))

  return sections


@graph_app.callback(
  Output('cy-panel', 'className'),
  Input('selected-node-store', 'data'),
)
def render_panel_className(selected_id):
  """On narrow viewports the panel is a full-screen drawer (see canopy.css)
  rather than an always-visible sidebar, so it needs an explicit open/closed
  state to animate in and out of - a separate callback rather than folding
  this into render_detail_panel's Output so that function's tested
  single-value return (the panel's children) doesn't have to change shape."""
  return 'cy-panel' + (' is-open' if selected_id else '')


# --- AI chat (optional - only registered when GEMINI_API_KEY is set) --------

if _CHAT_ENABLED:
  # A second, stricter budget than the analyze endpoint's 5/min - an LLM
  # call is the scarcest shared resource in the app (a quota-limited key
  # everyone using the deployed site shares), so this is deliberately tight.
  _CHAT_RATE_LIMIT_WINDOW_SECONDS = 60
  _CHAT_RATE_LIMIT_MAX_MESSAGES = 10

  @graph_app.callback(
    Output('chat-open-store', 'data'),
    Input('toggle-chat', 'n_clicks'),
    Input('chat-close', 'n_clicks'),
    State('chat-open-store', 'data'),
    prevent_initial_call=True,
  )
  def handle_chat_open_toggle(_toggle_clicks, _close_clicks, is_open):
    # chat-close always closes; toggle-chat flips - same _parse_triggered
    # helper handle_interaction already uses to tell two Input buttons apart.
    triggered_id, _ = _parse_triggered(dash.callback_context.triggered)
    if triggered_id == 'chat-close':
      return False
    return not is_open

  @graph_app.callback(
    Output('toggle-chat', 'className'),
    Input('chat-open-store', 'data'),
  )
  def render_chat_toggle(is_open):
    return 'cy-toggle cy-toggle--active' if is_open else 'cy-toggle'

  @graph_app.callback(
    Output('chat-expanded-store', 'data'),
    Input('chat-expand', 'n_clicks'),
    State('chat-expanded-store', 'data'),
    prevent_initial_call=True,
  )
  def handle_chat_expand_toggle(_n_clicks, is_expanded):
    return not is_expanded

  @graph_app.callback(
    Output('chat-expand', 'children'),
    Input('chat-expanded-store', 'data'),
  )
  def render_chat_expand_label(is_expanded):
    return 'collapse' if is_expanded else 'expand'

  @graph_app.callback(
    Output('chat-history-store', 'data'),
    Output('chat-input', 'value'),
    Input('chat-send', 'n_clicks'),
    Input('chat-input', 'n_submit'),
    State('chat-input', 'value'),
    State('chat-history-store', 'data'),
    State('analysis-id-store', 'data'),
    prevent_initial_call=True,
  )
  def handle_chat_submit(_n_clicks, _n_submit, message, history, analysis_id, request=None):
    """`request` is injected by django-plotly-dash - not a Dash Input/State,
    it's matched by parameter name against the real Django request for this
    callback dispatch (see DjangoDash.get_expanded_arguments), which is how
    a Dash callback gets at the caller's IP for rate limiting."""
    if not message or not message.strip() or not analysis_id:
      return dash.no_update, ''

    history = history or []

    if request is not None and is_rate_limited(
      request, 'chat-rate', _CHAT_RATE_LIMIT_MAX_MESSAGES, _CHAT_RATE_LIMIT_WINDOW_SECONDS,
    ):
      reply = "You're sending messages too quickly - wait a moment and try again."
    else:
      try:
        analysis = CommitAnalysis.objects.select_related('repo').get(pk=analysis_id)
      except CommitAnalysis.DoesNotExist:
        return dash.no_update, ''
      reply = ask_about_repo(analysis, history, message)

    new_history = history + [
      {'role': 'user', 'text': message.strip()},
      {'role': 'model', 'text': reply},
    ]
    return new_history, ''

  @graph_app.callback(
    Output('cy-chat-messages', 'children'),
    Input('chat-history-store', 'data'),
  )
  def render_chat_messages(history):
    if not history:
      return html.Div('Ask a question about this repo.', className='cy-chat__empty')
    return [
      html.Div(turn['text'], className=f"cy-chat__bubble cy-chat__bubble--{turn['role']}")
      for turn in history
    ]

  # Runs entirely in the browser: toggles the drawer's visibility class and
  # scrolls its message list to the bottom, same clientside-no-server-round-
  # trip pattern as the selection-highlight callback above.
  graph_app.clientside_callback(
    """
    function(isOpen, _history, isExpanded) {
      var drawer = document.getElementById('cy-chat');
      if (drawer) {
        drawer.classList.toggle('is-open', !!isOpen);
        drawer.classList.toggle('is-expanded', !!isExpanded);
      }
      var messages = document.getElementById('cy-chat-messages');
      if (messages) {
        messages.scrollTop = messages.scrollHeight;
      }
      return window.dash_clientside.no_update;
    }
    """,
    Output('chat-sync-store', 'data'),
    Input('chat-open-store', 'data'),
    Input('chat-history-store', 'data'),
    Input('chat-expanded-store', 'data'),
    prevent_initial_call=True,
  )
