import dash
import dash_cytoscape as cyto
from dash import dcc, html, Input, Output, State
from django.conf import settings
from django_plotly_dash import DjangoDash
from django_plotly_dash.dash_wrapper import PseudoFlask

from explorer.github_links import fetch_source_snippet, github_blob_url
from explorer.graph_data import ancestors_of, build_elements, callers_and_callees, children_of, index_children
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


# Hidden by default regardless of how deep a repo's package nesting goes -
# 'function' is the only kind whose visibility depends on the *kind* of its
# ancestors, not on raw graph depth (which would otherwise make a module's
# classes show or hide by default purely based on how many packages it
# happens to be nested under).
DEFAULT_HIDDEN_KINDS = {'function'}

graph_app = DjangoDash('RepoGraph')

graph_app.layout = html.Div([
  dcc.Store(id='analysis-id-store', data=None),
  dcc.Store(id='elements-store', data=[]),
  dcc.Store(id='expanded-store', data=[]),
  dcc.Store(id='repo-meta-store', data={}),
  dcc.Store(id='selected-node-store', data=None),
  dcc.Checklist(
    id='show-calls',
    options=[{'label': ' Show call edges', 'value': 'show'}],
    value=[],
  ),
  html.Div(id='graph-status'),
  html.Div([
    html.Div(
      cyto.Cytoscape(
        id='repo-graph',
        layout={'name': 'cose', 'animate': False},
        style={'width': '100%', 'height': '80vh'},
        elements=[],
        stylesheet=[
          {'selector': 'node', 'style': {'label': 'data(label)', 'font-size': '10px'}},
          {'selector': ':parent', 'style': {'background-opacity': 0.15, 'border-width': 1}},
          {'selector': 'edge', 'style': {'curve-style': 'bezier', 'target-arrow-shape': 'triangle', 'width': 1}},
          {'selector': 'node[kind = "repo"]', 'style': {'background-color': '#888'}},
          {'selector': 'node[kind = "package"]', 'style': {'background-color': '#7aa'}},
          {'selector': 'node[kind = "module"]', 'style': {'background-color': '#59a'}},
          {'selector': 'node[kind = "class"]', 'style': {'background-color': '#a75'}},
          {'selector': 'node[kind = "function"]', 'style': {'background-color': '#5a5'}},
          {'selector': 'edge[kind = "call"]', 'style': {'line-color': '#c33', 'target-arrow-color': '#c33'}},
        ],
      ),
      style={'width': '65%', 'display': 'inline-block', 'vertical-align': 'top'},
    ),
    html.Div([
      html.Div(id='detail-panel'),
      html.Div(id='source-snippet'),
    ], style={'width': '33%', 'display': 'inline-block', 'vertical-align': 'top', 'padding': '0 1em'}),
  ]),
])


@graph_app.callback(
  Output('elements-store', 'data'),
  Output('graph-status', 'children'),
  Output('repo-meta-store', 'data'),
  Input('analysis-id-store', 'data'),
)
def load_elements(analysis_id):
  if not analysis_id:
    return [], 'No analysis selected.', {}

  try:
    analysis = CommitAnalysis.objects.select_related('repo').get(pk=analysis_id)
  except CommitAnalysis.DoesNotExist:
    return [], f'No analysis found for id {analysis_id}.', {}

  elements = build_elements(analysis.graph, repo_label=analysis.repo.name)
  status = f'{analysis.repo.name} @ {analysis.commit_hash[:7]} - click a box to expand it.'
  repo_meta = {'url': analysis.repo.url, 'commit_hash': analysis.commit_hash}
  return elements, status, repo_meta


def _resolve_navigation_target(triggered_id, triggered_value, tapped):
  """Given Dash's `callback_context.triggered_id`/the triggering prop's
  value, and the tapNodeData payload, return the node id that should
  become selected/revealed, or None if this invocation shouldn't do
  anything (e.g. the initial call, an untapped/empty event, or - see
  below - a nav-btn that wasn't actually clicked).

  A pattern-matching ALL input re-fires the callback not only on a real
  click but also whenever the *set* of matched components changes - e.g.
  render_detail_panel mounting a fresh batch of caller/callee buttons for
  a newly-selected node. Dash reports one of those freshly-mounted (never
  clicked) buttons as the trigger in that case too, with its n_clicks at
  the value it was just created with (0). Only a real click increments
  n_clicks, so requiring a truthy triggered_value is what tells the two
  apart - without it, selecting a node can spuriously auto-navigate to
  one of its own callees, which can cascade further.
  """
  if triggered_id == 'repo-graph':
    return tapped.get('id') if tapped else None
  if isinstance(triggered_id, dict) and triggered_id.get('type') == 'nav-btn':
    return triggered_id.get('target') if triggered_value else None
  return None


def _compute_navigation_update(target_id, expanded, elements):
  """Returns (new_expanded, target_id). new_expanded is None if `expanded`
  doesn't actually need to change (caller should use dash.no_update)."""
  if target_id is None:
    return None, None

  # A caller/callee "navigate to" click can target a node that isn't
  # currently visible at all, unlike a direct graph tap (which can only
  # ever target an already-visible node) - so ancestors must be revealed
  # too, not just the target's own children.
  to_reveal = ancestors_of(elements, target_id)
  if children_of(elements, target_id):
    to_reveal = to_reveal + [target_id]

  needed = [node_id for node_id in to_reveal if node_id not in expanded]
  if not needed:
    return None, target_id
  return expanded + needed, target_id


@graph_app.callback(
  Output('expanded-store', 'data'),
  Output('selected-node-store', 'data'),
  Input('repo-graph', 'tapNodeData'),
  Input({'type': 'nav-btn', 'role': dash.ALL, 'target': dash.ALL}, 'n_clicks'),
  State('expanded-store', 'data'),
  State('elements-store', 'data'),
  State('selected-node-store', 'data'),
  prevent_initial_call=True,
)
def navigate(tapped, _nav_clicks, expanded, elements, currently_selected):
  triggered = dash.callback_context.triggered[0] if dash.callback_context.triggered else {}
  target_id = _resolve_navigation_target(dash.callback_context.triggered_id, triggered.get('value'), tapped)

  if target_id is None or target_id == currently_selected:
    return dash.no_update, dash.no_update

  new_expanded, selected_id = _compute_navigation_update(target_id, expanded, elements)
  return (new_expanded if new_expanded is not None else dash.no_update), selected_id


@graph_app.callback(
  Output('repo-graph', 'elements'),
  Input('elements-store', 'data'),
  Input('expanded-store', 'data'),
  Input('show-calls', 'value'),
)
def render_visible_elements(elements, expanded, show_calls_value):
  # children_by_parent is needed unconditionally, not just when something is
  # expanded: a function that itself contains a nested class/function (a
  # locally-defined class, or a nested def) is a container, not a leaf, and
  # must stay visible by default so its children aren't left with a parent
  # that got hidden - Cytoscape requires every visible node's parent to also
  # be visible. Only childless ("leaf") functions are hidden by default.
  children_by_parent = index_children(elements)

  hidden_ids = {
    el['data']['id']
    for el in elements
    if el['data'].get('kind') in DEFAULT_HIDDEN_KINDS and not children_by_parent.get(el['data']['id'])
  }

  visible_ids = {
    el['data']['id']
    for el in elements
    if el['data'].get('kind') != 'call' and el['data']['id'] not in hidden_ids
  }

  for parent_id in expanded:
    visible_ids |= {c['data']['id'] for c in children_by_parent.get(parent_id, [])}

  visible = [el for el in elements if el['data'].get('kind') != 'call' and el['data']['id'] in visible_ids]

  if 'show' in (show_calls_value or []):
    visible += [
      el for el in elements
      if el['data'].get('kind') == 'call'
      and el['data']['source'] in visible_ids
      and el['data']['target'] in visible_ids
    ]

  return visible


def _find_element(elements, node_id):
  return next((el for el in elements if el['data']['id'] == node_id), None)


def _nav_button(role, target_id, elements):
  # id carries role and target as separate keys, not encoded into one
  # string - a node that is both a caller and a callee of the selected
  # node (mutual recursion) needs two distinct buttons, and Dash requires
  # every component id to be unique.
  target = _find_element(elements, target_id)
  label = target['data']['label'] if target else target_id
  title = target['data'].get('name', target_id) if target else target_id
  return html.Button(label, id={'type': 'nav-btn', 'role': role, 'target': target_id}, title=title, n_clicks=0)


@graph_app.callback(
  Output('detail-panel', 'children'),
  Input('selected-node-store', 'data'),
  State('elements-store', 'data'),
  State('repo-meta-store', 'data'),
)
def render_detail_panel(selected_id, elements, repo_meta):
  if not selected_id:
    return 'Click a node to see its details.'

  el = _find_element(elements, selected_id)
  if el is None:
    return dash.no_update

  data = el['data']
  rows = [
    html.H3(data.get('name', data['label'])),
    html.P(f"kind: {data['kind']}"),
  ]

  if data.get('docstring'):
    rows.append(html.P(data['docstring']))

  if data.get('relative_path'):
    line_range = f" (lines {data['lineno']}-{data['end_lineno']})" if data.get('end_lineno') else ''
    rows.append(html.P(f"{data['relative_path']}{line_range}"))

  if data.get('kind') == 'function':
    rows.append(html.P(
      f"complexity: {data.get('complexity')} - loc: {data.get('loc')} - "
      f"fan-in: {data.get('fan_in')} - fan-out: {data.get('fan_out')}"
    ))

  repo_url = repo_meta.get('url') if repo_meta else None
  if repo_url and data.get('relative_path'):
    blob_url = github_blob_url(
      repo_url, repo_meta['commit_hash'], data['relative_path'], data.get('lineno'), data.get('end_lineno'),
    )
    if blob_url:
      rows.append(html.A('View on GitHub', href=blob_url, target='_blank'))

  callers, callees = callers_and_callees(elements, selected_id)
  if callers:
    rows.append(html.P('Called by:'))
    rows.append(html.Div([_nav_button('caller', c, elements) for c in callers]))
  if callees:
    rows.append(html.P('Calls:'))
    rows.append(html.Div([_nav_button('callee', c, elements) for c in callees]))

  return rows


@graph_app.callback(
  Output('source-snippet', 'children'),
  Input('selected-node-store', 'data'),
  State('elements-store', 'data'),
  State('repo-meta-store', 'data'),
)
def render_source_snippet(selected_id, elements, repo_meta):
  if not selected_id or not repo_meta or not repo_meta.get('url'):
    return ''

  el = _find_element(elements, selected_id)
  if el is None or not el['data'].get('relative_path'):
    return ''

  data = el['data']
  snippet = fetch_source_snippet(
    repo_meta['url'], repo_meta['commit_hash'], data['relative_path'], data.get('lineno'), data.get('end_lineno'),
  )
  if snippet is None:
    return 'Source unavailable.'
  return html.Pre(snippet)
