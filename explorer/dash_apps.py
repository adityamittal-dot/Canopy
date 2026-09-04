import dash
import dash_cytoscape as cyto
from dash import dcc, html, Input, Output, State
from django.conf import settings
from django_plotly_dash import DjangoDash
from django_plotly_dash.dash_wrapper import PseudoFlask

from explorer.graph_data import build_elements, children_of, index_children
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
  dcc.Checklist(
    id='show-calls',
    options=[{'label': ' Show call edges', 'value': 'show'}],
    value=[],
  ),
  html.Div(id='graph-status'),
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
])


@graph_app.callback(
  Output('elements-store', 'data'),
  Output('graph-status', 'children'),
  Input('analysis-id-store', 'data'),
)
def load_elements(analysis_id):
  if not analysis_id:
    return [], 'No analysis selected.'

  try:
    analysis = CommitAnalysis.objects.select_related('repo').get(pk=analysis_id)
  except CommitAnalysis.DoesNotExist:
    return [], f'No analysis found for id {analysis_id}.'

  elements = build_elements(analysis.graph, repo_label=analysis.repo.name)
  return elements, f'{analysis.repo.name} @ {analysis.commit_hash[:7]} - click a box to expand it.'


@graph_app.callback(
  Output('expanded-store', 'data'),
  Input('repo-graph', 'tapNodeData'),
  State('expanded-store', 'data'),
  State('elements-store', 'data'),
)
def expand_on_click(tapped, expanded, elements):
  if not tapped:
    return dash.no_update

  node_id = tapped.get('id')
  if node_id in expanded or not children_of(elements, node_id):
    return dash.no_update

  return expanded + [node_id]


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