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
      timeout=120,
    )
  except FileNotFoundError as exc:
    raise CloneError("git is not installed or not on PATH") from exc
  except subprocess.TimeoutExpired as exc:
    raise CloneError(f"timed out cloning {url}") from exc
  except subprocess.CalledProcessError as exc:
    raise CloneError(f"failed to clone {url}: {exc.stderr.strip()}") from exc

  try:
    result = subprocess.run(
      ["git", "rev-parse", "HEAD"],
      cwd=dest,
      check=True,
      capture_output=True,
      text=True,
      timeout=15,
    )
  except subprocess.TimeoutExpired as exc:
    raise CloneError("timed out resolving commit hash") from exc
  except subprocess.CalledProcessError as exc:
    raise CloneError(f"failed to resolve commit hash: {exc.stderr.strip()}") from exc

  commit_hash = result.stdout.strip()
  return dest, commit_hash


def get_remote_head_commit(url: str) -> str:
  """Resolve the HEAD commit hash of `url` without cloning it."""
  try:
    result = subprocess.run(
      ["git", "ls-remote", url, "HEAD"],
      check=True,
      capture_output=True,
      text=True,
      timeout=30,
    )
  except FileNotFoundError as exc:
    raise CloneError("git is not installed or not on PATH") from exc
  except subprocess.TimeoutExpired as exc:
    raise CloneError(f"timed out reaching {url}") from exc
  except subprocess.CalledProcessError as exc:
    raise CloneError(f"failed to reach {url}: {exc.stderr.strip()}") from exc

  line = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
  if not line:
    raise CloneError(f"no HEAD ref found for {url} (empty repo or wrong URL)")

  return line.split()[0]
