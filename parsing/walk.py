import os

from parsing.languages import LANGUAGE_REGISTRY

SKIP_DIRS = {'.git', 'venv', '.venv', 'node_modules', '__pycache__', 'target', 'dist', 'build'}

def find_source_files(root: str) -> list[str]:
  """Walk `root` and return the full path of every file whose extension has
  a registered LanguageAnalyzer, skipping SKIP_DIRS and hidden directories.
  A file with an unrecognized extension is never an error - it just doesn't
  contribute nodes to the graph (see parsing.pipeline.analyze_repo), same as
  any non-.py file was silently skipped before multi-language support."""
  source_files = []

  for dirpath, dirnames, filenames in os.walk(root):
    dirnames[:] = [
      d for d in dirnames
      if d not in SKIP_DIRS and not d.startswith('.')
    ]

    for filename in filenames:
      if os.path.splitext(filename)[1] in LANGUAGE_REGISTRY:
        source_files.append(os.path.join(dirpath, filename))

  return source_files