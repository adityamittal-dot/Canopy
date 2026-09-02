import ast
import tokenize

class ParseError(Exception):
  """Raised when a file's source can;t be read or parsed."""
  
def parse_file(path: str) -> ast.Module:
  """Read `path` and return its parsed AST. Rasies ParseError on failure."""
  try:
    with tokenize.open(path) as f:
      source = f.read()
    return ast.parse(source, filename=path)
  except (SyntaxError, OSError, UnicodeDecodeError) as exc:
    raise ParseError(f"Failed to parse {path}: {exc}") from exc
  
def parse_files(paths: list[str]) -> tuple[dict[str, ast.Module], list[tuple[str, ParseError]]]:
  """Parse every path in `paths`. Returns (path -> AST for Successes, list of (path, error) for failures)."""
  trees = {}
  failures = []
  
  for path in paths:
    try:
      trees[path] = parse_file(path)
    except ParseError as exc:
      failures.append((path, exc))
      
  return trees, failures