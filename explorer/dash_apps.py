import json
import re

import dash
from dash import dcc, html, Input, Output, State
from django.conf import settings
from django.templatetags.static import static
from django_plotly_dash import DjangoDash
from django_plotly_dash.dash_wrapper import PseudoFlask

from explorer.github_links import fetch_source_snippet, github_blob_url
from explorer.graph_data import (
  build_elements, callers_and_callees, index_children, subtree_node_count,
  noise_ids_for_tests, vendor_noise_ids,
)
from explorer.models import CommitAnalysis

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

graph_app.layout = html.Div(className='cy-app', children=[
  dcc.Store(id='analysis-id-store', data=None),
  dcc.Store(id='elements-store', data=[]),
  dcc.Store(id='repo-meta-store', data={}),
  dcc.Store(id='expanded-store', data=[]),
  dcc.Store(id='selected-node-store', data=None),
  dcc.Store(id='show-edges-store', data=True),
  dcc.Store(id='hide-tests-store', data=True),
  dcc.Store(id='hide-vendor-store', data=True),

  html.Div(className='cy-shell', children=[
    html.Div(id='cy-header'),
    html.Div(className='cy-toolbar', children=[
      html.Div(className='cy-search', children=[
        html.Span('search', className='cy-search__label'),
        html.Div(className='cy-search__box', children=[
          html.Span('/', className='cy-search__prefix'),
          dcc.Input(id='search-input', type='text', placeholder='qualified name', debounce=False, n_submit=0),
        ]),
      ]),
      html.Span(className='cy-vdivider'),
      html.Button('edges: on', id='toggle-edges', className='cy-toggle cy-toggle--active'),
      html.Button('tests: hide', id='toggle-tests', className='cy-toggle cy-toggle--active'),
      html.Button('vendor: hide', id='toggle-vendor', className='cy-toggle cy-toggle--active'),
      html.Div(id='cy-breadcrumb', className='cy-breadcrumb'),
    ]),
    html.Div(className='cy-body', children=[
      html.Div(className='cy-main', children=[
        html.Div(className='cy-canvas', children=[
          html.Div(id='cy-tag', className='cy-canvas__tag'),
          html.Div(id='cy-tree'),
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
    html.A(href='/', className='cy-header__logo', children=[
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
  return html.Button(data['label'], id=_click_id('select', node_id), className=className, title=data.get('name', data['label']))


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
    ], id=_click_id('select', node_id), className=label_className),
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


@graph_app.callback(
  Output('cy-tree', 'children'),
  Input('elements-store', 'data'),
  Input('expanded-store', 'data'),
  Input('hide-tests-store', 'data'),
  Input('hide-vendor-store', 'data'),
  Input('selected-node-store', 'data'),
)
def render_tree(elements, expanded, hide_tests, hide_vendor, selected_id):
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
  boxes = [
    _render_container(child['data']['id'], elements, children_index, expanded, test_noise, vendor_noise, selected_id)
    for child in containers
  ]
  boxes.extend(_ghost_box(ghost_data, category, elements) for ghost_data, category in ghosts)
  return html.Div(boxes, className='cy-grid')


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
      html.Span(data['kind'], className=f"cy-k-{data['kind']}"),
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
