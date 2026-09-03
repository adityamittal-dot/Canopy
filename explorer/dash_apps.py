from dash import html, Input, Output
from django.conf import settings
from django_plotly_dash import DjangoDash
from django_plotly_dash.dash_wrapper import PseudoFlask

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