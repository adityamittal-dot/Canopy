# Canopy — Handoff

_Last updated: 2026-09-03_

## What this is

Paste a GitHub repo URL in, get a hierarchical, explorable diagram of the codebase: repo -> modules -> files -> classes -> functions, down to individual functions as leaf nodes, with callers/callees shown for each one. See `README.md` for the full pitch, competitive landscape, and tech stack rationale; `canopy-notes.md` for the original planning doc.

## Current status: parsing engine complete, Django app not started

The **entire parsing pipeline is built, tested, and merged into `dev`** — this is a pure-Python, Django-free layer that takes a repo URL and produces the full structural graph as data. Nothing beyond a bare Django scaffold exists yet for the actual web app / visualization.

### What's built (`parsing/` package)

| File | What it does |
|---|---|
| `clone.py` | `clone_repo(url)` — shallow `git clone --depth 1` into a temp dir, returns `(local_path, commit_hash)`. Raises `CloneError` on failure instead of a raw traceback. |
| `walk.py` | `find_python_files(root)` — walks a directory, returns every `.py` file path. Prunes `.git`/`venv`/`node_modules`/`__pycache__`/hidden dirs during the walk (not after), so it never descends into them. |
| `parse.py` | `parse_file(path)` / `parse_files(paths)` — reads via `tokenize.open` (respects PEP 263 encoding declarations) and runs `ast.parse()`. Batch version keeps going past individual failures, returns `(successes, failures)` separately. |
| `extract.py` | The core. `Symbol` dataclass (kind, name, file, docstring, lineno, end_lineno, calls, complexity) + `SymbolVisitor`, an `ast.NodeVisitor` that walks a module once and records every class/function definition, including nesting, via a scope stack for correct qualified names. |
| `calls.py` | `extract_calls(node)` — walks a function's body for `Call` nodes, returns dotted names (`self.foo.bar`). Stops at nested def boundaries so a nested function's calls aren't misattributed. |
| `imports.py` | `extract_imports(tree)` — every `import`/`from...import` as a dotted string, including relative imports (`.pkg.x`, `..pkg.x`). Not used for resolution yet, just captured. |
| `symbol_table.py` | `build_symbol_table(symbols)` — flattens every file's symbols into one `{qualified_name: Symbol}` dict spanning the repo. |
| `resolve.py` | `resolve_calls(table)` — the call-graph builder. Matches by bare (last-component) name; same-file candidates preferred over repo-wide. Repo-wide fallback is restricted to calls that look local (bare names or `self.`/`cls.`-prefixed) — a dotted call into an imported module won't get guessed at. Unmatched calls become explicit unresolved edges (`callee=None`), never dropped. |
| `metrics.py` | `compute_loc`, `compute_complexity` (1 + branches: if/for/while/except/boolean-operator, stops at nested defs), `compute_fan_in_out` (from resolved edges only). |
| `pipeline.py` | `analyze_repo(url)` — orchestrates all of the above into one call. Returns `{commit_hash, parse_failures, nodes, edges, imports}`, fully JSON-serializable. |
| `scripts/dump_symbols.py` | CLI: `python -m scripts.dump_symbols <file> --module-name x` dumps one file's extracted symbols as JSON. Useful for spot-checking. |

**Test suite:** 26 tests in `tests/`, covering every module above plus fixtures for edge cases (decorators, lambdas, comprehensions, dunders, async, f-strings, walrus operator, `match`/`case`). Run with:
```
python -m pytest tests/ -v
```

### Validated against real code

Ran `analyze_repo` end-to-end against `pallets/flask`: 0 parse failures across the entire repo, 1705 symbols extracted, 3282 call sites found, ~20% resolved (the rest are legitimately external stdlib/third-party calls, correctly left unresolved rather than guessed).

### Known limitation, not fixed

Call resolution matches by bare method/function name. Two different classes with an identically-named method **in the same file** can still collide (whichever is found first in the symbol table wins) — this needs class-scoped resolution to fix properly, which wasn't done. Cross-file collisions with common names were mitigated (see `resolve.py`'s `_looks_local` check) but same-file collisions remain a real, accepted gap.

## Django app: bare scaffold only

- `canopy/` (project) + `explorer/` (app) exist via `django-admin startproject`/`startapp`, wired into `INSTALLED_APPS`.
- `explorer/models.py` has `Repo` (url, name, created_at) and `CommitAnalysis` (repo FK, commit_hash, graph JSONField, created_at, unique_together on repo+commit_hash) — hand-written by the project owner, migrated successfully against Postgres.
- `explorer/admin.py` is still empty boilerplate — models aren't registered yet.
- `django-plotly-dash` is installed (`requirements.txt`) but **not** wired into `INSTALLED_APPS`/middleware/URLs yet.
- No views, no URLs beyond `/admin/`, no templates, no Dash app, nothing connecting `parsing/` to the Django app at all yet.

## What's next, in order

1. **Wire `django-plotly-dash`** into `INSTALLED_APPS`, middleware (`django_plotly_dash.middleware.BaseMiddleware`), static finders, and URLs (`django_plotly_dash.urls`). Confirm a minimal Dash "hello world" renders inside a Django page before building the real graph on top.
2. **Register `Repo`/`CommitAnalysis` in `explorer/admin.py`** — trivial, but needed to inspect parsed data without custom tooling while building the rest.
3. **Build the "analyze a repo" view**: accepts a URL, calls `parsing.pipeline.analyze_repo`, saves the result into a `CommitAnalysis` row. Check for an existing `CommitAnalysis` (same repo + commit hash) before re-running the pipeline — that's the caching layer the models were designed for.
4. **Basic input error handling** in that view: invalid/unreachable URL (`CloneError` from `parsing/clone.py` already gives a clean exception to catch), private repos (not supported, no OAuth yet), repos with zero Python files.
5. **Register a `django-plotly-dash` app for the graph** and wire up `dash-cytoscape` to render a `CommitAnalysis`'s `nodes`/`edges` JSON — hierarchical/dagre layout, collapsed past depth 2 by default.
6. **Node-click detail panel**: docstring, file path, line range, source snippet (pulled from the cloned repo or GitHub's raw API), LOC/complexity, clickable callers/callees, a GitHub deep link.
7. **Cross-cutting "who calls this anywhere in the repo" view**, search-by-name, noise filters (tests/vendor/`__pycache__`/venv, default hidden).
8. **Polish + deploy**: README already exists; still need deployment (Railway/Render/Fly.io + managed Postgres), Gunicorn + WhiteNoise (already in `requirements.txt`/`Dockerfile`), basic rate limiting on the analyze endpoint, and real-world testing against repos not used during development.

## Running it locally

```bash
venv\Scripts\Activate.ps1          # Windows
pip install -r requirements.txt
docker compose up -d db            # Postgres container
python manage.py migrate
python manage.py runserver
```
Or the whole stack via `docker compose up --build`.

## Git workflow / conventions in use

- Branch off `dev` (the default branch); `master` is production, updated separately, not day-to-day.
- **No commit/PR attribution** (no `Co-Authored-By`, no "Generated with Claude Code" footer) — an explicit, standing instruction from the project owner that overrides any default tooling behavior suggesting otherwise.
- **No Jira/ticket references anywhere** in commits, branches, or PR descriptions — the project moved off ticket-based tracking; this file (and `canopy-dev-notes.md`) is the source of truth for status instead.
- Batch related work into one PR rather than one PR per small step (this was a correction partway through — the parsing pipeline was originally built as 12 separate stacked PRs, which was too granular).
- If stacking branches for related work, be careful with `gh pr merge --delete-branch` run back-to-back across a deep stack — it can race GitHub's base-branch retargeting and auto-close PRs whose base branch just got deleted. If that happens: verify no content was lost with `git diff --stat` between the stray branch and `dev` before deleting anything, then merge the stack's tip directly into `dev` with a plain `git merge`.

## Environment notes (Windows-specific gotchas hit during setup)

- VS Code's integrated terminal caches `PATH` at process launch — installing something new (Docker Desktop, `gh` CLI) won't be visible until VS Code is **fully quit and reopened**, not just "Reload Window" or a new terminal tab.
- Docker Desktop now installs per-user at `C:\Users\<user>\AppData\Local\Programs\DockerDesktop\`, not the old machine-wide `C:\Program Files\Docker\`.
- `gh` CLI is installed and authenticated (`gh auth status` to verify) — used for PR creation/management throughout.
