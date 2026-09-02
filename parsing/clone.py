import subprocess
import tempfile

class CloneError(Exception):
  """Raised when a repo can't be cloned."""
  
def clone_repo(url: str) -> tuple[str, str]:
  """Shallow-clone `url` into a temp dir. Returns (local_path, commit_hash)."""
  dest = tempfile.mkdtemp()
  
  try:
    subprocess.run(
      ["git", "clone", "--depth", "1", url, dest],
      check=True,
      capture_output=True,
      text=True,
    )
  except FileNotFoundError as exc:
    raise CloneError("git is not installed or not on PATH") from exc
  except subprocess.CalledProcessError as exc:
    raise CloneError(f"failed to clone {url}: {exc.stderr.strip()}") from exc
  
  try:
    result = subprocess.run(
      ["git", "rev-parse", "HEAD"],
      cwd=dest,
      check=True,
      capture_output=True,
      text=True,
    )
  except subprocess.CalledProcessError as exc:
    raise CloneError(f"failed to resolve commit hash: {exc.stderr.strip()}") from exc
  
  commit_hash = result.stdout.strip()
  return dest, commit_hash