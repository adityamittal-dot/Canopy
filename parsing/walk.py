import os

SKIP_DIRS = {'.git', 'venv', 'node_modules','__pycache__'}

def find_python_files(root: str) -> list[str]:
  """Walk `root` and return the full path of every .py file found,
  skipping SKIP_DIRS and hidden directories."""
  py_files = []
  
  for dirpath, dirnames, filenames in os.walk(root):
    dirnames[:] = [
      d for d in dirnames
      if d not in SKIP_DIRS and not d.startswith('.')
    ]
    
    for filename in filenames:
      if filename.endswith('.py'):
        py_files.append(os.path.join(dirpath, filename))
        
  return py_files