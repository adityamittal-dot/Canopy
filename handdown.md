# Canopy — Handoff

_Last updated: 2026-09-09_

## What this is

Paste a GitHub repo URL in, get a hierarchical, explorable diagram of the codebase: repo -> packages -> modules -> classes -> functions, down to individual functions as leaf nodes, with callers/callees shown for each one. Supports Python, JavaScript, TypeScript, Go, Java, Rust, C, C++, Ruby, PHP, and C# in the same repo at once. See `README.md` for the full pitch, competitive landscape, and tech stack rationale; `canopy-notes.md` for the original planning doc.

## Current status: live and deployed

**<https://canopy-v7hb.onrender.com/>** — Render web service (Docker) + Render managed Postgres. The bare domain redirects to `/analyze/`, the dashboard/landing page.

Every phase in the original roadmap is done: parsing engine, Django app, exploration features (search/noise filters/cross-cutting caller-callee view), UI redesign, and deployment.

### What's built (`parsing/` package)

Still a pure-Python, Django-free layer. As of this session, multi-language: every file is dispatched to the `LanguageAnalyzer` registered for its extension (`parsing/languages/`) rather than assuming Python everywhere. Downstream of extraction (`resolve.py`, `metrics.py`, `symbol_table.py`, `explorer/graph_data.py`) was already language-agnostic before this change and needed no rework — it was already built around the generic `Symbol`/`Edge` shape.

| File | What it does |
|---|---|
| `clone.py` | `clone_repo(url)` — shallow `git clone --depth 1` into a temp dir, returns `(local_path, commit_hash)`. Raises `CloneError` on failure instead of a raw traceback. Also `get_remote_head_commit(url)` — `git ls-remote`, no full clone, used for the cache-check before deciding whether to re-analyze. |
| `walk.py` | `find_source_files(root)` — walks a directory, returns every file whose extension has a registered `LanguageAnalyzer`. Prunes `.git`/`venv`/`.venv`/`node_modules`/`__pycache__`/`target`/`dist`/`build`/hidden dirs during the walk (not after), so it never descends into them. |
| `parse.py` | `parse_file(path)` / `parse_files(paths)` — the Python-specific reader: `tokenize.open` (respects PEP 263 encoding declarations) + `ast.parse()`. Batch version keeps going past individual failures. `ParseError` is shared by every language's analyzer, not just Python's. |
| `extract.py` | `Symbol` dataclass (kind, name, file, docstring, lineno, end_lineno, calls, complexity, **language**) + `SymbolVisitor`, the original `ast.NodeVisitor` — unchanged, still Python's own extractor. |
| `calls.py` / `imports.py` | Python-specific `ast.Call`/`ast.Import` walkers, unchanged. |
| `languages/base.py` | `LanguageAnalyzer` protocol (`parse`/`extract_symbols`/`extract_imports`) + `LANGUAGE_REGISTRY` (extension -> analyzer) + `register()`/`analyzer_for()`. |
| `languages/python_lang.py` | Thin adapter wrapping `extract.py`/`calls.py`/`imports.py`/`parse.py` behind the `LanguageAnalyzer` interface — Python's own path is otherwise untouched. |
| `languages/treesitter.py` | **The generic engine.** One `TreeSitterAnalyzer`, parameterized per language by a data-only `TreeSitterLanguageSpec` (which node types are functions/classes, which field holds a name, branch/call/comment/import node types) instead of a hand-written visitor per language. Handles definition nesting, docstring-comment attachment (with adjacency tolerant of grammars that do/don't include a comment's trailing newline in its span), calls (callee = the raw source text of the callee field, then `.`/`::`/`->`-normalized so `resolve.bare_name` keeps working unmodified), complexity (branch-node counting, stops at nested def boundaries), plus two small per-language escape hatches: `transparent_scope_types` (Rust's `impl Widget { }` isn't a definition itself but its methods nest under `Widget`) and `receiver_field`/`definition_filter` (Go's receiver methods and struct-vs-alias `type_spec` disambiguation). |
| `languages/specs.py` | The 10 tree-sitter `TreeSitterLanguageSpec`s (JS, TS, Go, Java, Rust, C, C++, Ruby, PHP, C#) + registers the Python adapter. Node type/field names came from parsing real samples through each grammar during development (these PyPI packages ship no `node-types.json`), not from docs alone. |
| `symbol_table.py` | `build_symbol_table(symbols)` — flattens every file's symbols into one `{qualified_name: Symbol}` dict spanning the repo. Unchanged. |
| `resolve.py` | `resolve_calls(table)` — the call-graph builder. Matches by bare (last-component) name; same-file candidates preferred over repo-wide. Repo-wide fallback restricted to calls that look local (`self.`/`cls.`/`this.`/`this->`/`$this.`/`$this->` prefixes, or no dot at all). **New:** candidates are also restricted to the caller's own `language` — a same-named function in a different language never cross-resolves by coincidence in a polyglot repo. |
| `metrics.py` | `compute_loc`, `compute_complexity` (Python-specific: 1 + branches + boolean-operator fan-out, stops at nested defs), `compute_fan_in_out` (language-agnostic, from resolved edges only). Non-Python languages get a simpler "rough" complexity (1 + branch-node count only, no boolean-operator fan-out) computed inline in `treesitter.py`. |
| `pipeline.py` | `analyze_repo(url)` = `clone_repo` + `analyze_local_repo(repo_root, commit_hash)`. The latter is split out so the parse/dispatch/resolve/measure pipeline is testable against a local directory without a real clone (see `tests/test_multilang_pipeline.py`). Dispatches each file to `languages.analyzer_for(file)`; an unrecognized extension was never even collected by `find_source_files`, so it contributes nothing rather than erroring — "any type of repo" degrades gracefully. |
| `scripts/dump_symbols.py` | CLI: `python -m scripts.dump_symbols <file> --module-name x` dumps one file's extracted symbols as JSON — still Python-only, unchanged. |

**Known limitations, not fixed:**
- Call resolution matches by bare method/function name — two different classes with an identically-named method in the same file can still collide. Cross-file collisions with common names are mitigated (`resolve.py`'s `_looks_local` check, now also language-restricted); same-file collisions remain a real, accepted gap.
- `.h` headers are always parsed with the C grammar (no reliable way to distinguish a C++ header by extension alone) — a C++-only header may parse incompletely.
- Non-Python languages get "rough" complexity (branch-node count only); Python alone also counts boolean-operator fan-out.

### Django app (`explorer/`)

- `explorer/models.py`: `Repo` (url, name, created_at) and `CommitAnalysis` (repo FK, commit_hash, graph JSONField, unique on repo+commit_hash) — this is the analysis cache.
- `explorer/views.py`: `analyze` (accepts a URL, checks the remote HEAD commit against a cached `CommitAnalysis` before re-running the pipeline, has SSRF guards against private/loopback hosts, and a per-IP rate limit of 5 submissions/minute) and `graph_view` (renders the Dash-embedded explorer for one analysis).
- `explorer/dash_apps.py`: the interactive explorer itself — see "UI redesign" below.
- `explorer/github_links.py`: builds GitHub blob deep-links and fetches live source snippets from `raw.githubusercontent.com` for the detail panel (optional `GITHUB_TOKEN` env var raises the request allowance).

### UI redesign

The original Cytoscape.js graph view was fully replaced with a nested box/pill tree (repo -> packages -> modules -> classes -> functions), traced detail-for-detail from a user-supplied reference design (scraped with Playwright — computed styles, raw stylesheet rules, rendered DOM/class structure) rather than an original or AI-generated palette.

- `explorer/static/explorer/canopy.css` / `landing.css`: hand-written CSS design system (no build step) — OKLCH color tokens, JetBrains Mono/IBM Plex Mono typography, component recipes for boxes, pills, breadcrumbs, toasts, the detail panel. Loaded via `DjangoDash`'s `external_stylesheets` constructor arg, not Dash's `assets/` folder convention (confirmed non-functional under `django-plotly-dash`, which never forwards a custom `assets_folder`).
- Packages/modules/classes always render in full; only each container's function-pill list collapses behind an expand toggle. Two independent filters (tests, vendored deps) render matching subtrees as dimmed "ghost" placeholders rather than omitting them silently.
- Three integration bugs specific to `django-plotly-dash`, only reachable through a real browser click (never through calling the pure helper functions directly): the iframe embed defaulting to a squeezed 10%-aspect-ratio sliver (`{% plotly_app %}`'s `ratio=0.1` default — fixed with an explicit `height="100vh"`), `django-plotly-dash`'s `CallbackContext` shim missing Dash's `triggered_id` convenience property (fixed with a `_parse_triggered()` helper that parses the component id out of `callback_context.triggered` by hand), and top-level noise packages disappearing instead of ghosting (fixed by unifying `render_tree`'s top-level loop with `_render_container`'s nested-child logic via a shared `_partition_children` helper).

### Performance

Profiled against a live `pallets/flask` analysis (1733 nodes) and found selecting a node — the single most frequent interaction — was re-rendering and re-serializing the *entire* tree server-side (an ~90-100KB Dash JSON payload per click), because `selected-node-store` was a Dash `Input` on `render_tree` purely to toggle an `is-selected` class.

Fixed by moving selection highlighting to a Dash `clientside_callback` (pure JS, no server round-trip) that toggles the class directly via a plain `data-node-id` attribute on the box/pill buttons. `render_tree` keeps the selected id as a `State` (so a structural re-render — expand/collapse, filter toggle — still bakes in the right highlight) but no longer treats a selection change as a reason to rebuild the whole tree. Also added `GZipMiddleware` — Dash's JSON payloads are mostly repeated key names and compress well.

Not done: lazy-rendering containers themselves (currently only function-pill lists collapse; packages/modules/classes always render in full, which is the biggest remaining lever for very large repos).

### Deployment

Live on **Render**: a Docker-based web service + Render's managed Postgres plugin, connected to the `dev` branch (auto-deploys on push).

Settings (`canopy/settings.py`) are env-driven so the same image works locally, in `docker-compose`, or on any host:

| Env var | Purpose |
|---|---|
| `SECRET_KEY` | Falls back to a committed dev-only value locally; must be set in production. |
| `DJANGO_DEBUG` | `"True"`/unset. Defaults to `False` (secure by default) — local dev/tests need this set explicitly (docker-compose already does). |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated. |
| `CSRF_TRUSTED_ORIGINS` | Optional — auto-derived from `DJANGO_ALLOWED_HOSTS` (same hosts, `https://` prefixed) if unset. |
| `DATABASE_URL` | What Render's/Railway's Postgres plugin injects; parsed with stdlib `urlparse`. Falls back to split `DB_*` vars (what local `docker-compose` uses) if unset. |
| `GITHUB_TOKEN` | Optional, raises the rate-limit allowance for the source-snippet fetch. |

Two bugs found only by actually trying to deploy, not visible from reading the code:

- `collectstatic` had no `STATIC_ROOT` to write to at all — the Dockerfile ran it, but it was always going to fail.
- `explorer/dash_apps.py` calls Django's `static()` at **Python import time** (`DjangoDash(..., external_stylesheets=[static(...)])`), which runs as a side effect of `collectstatic` importing the app — before `collectstatic` has copied anything into `STATIC_ROOT` or built the manifest that lookup depends on. Fixed with `canopy/storage.py`, a small `ManifestStaticFilesStorage` subclass that falls back to the unhashed filename for that one lookup instead of crashing the whole command on a fresh checkout.

Also found live, after the first real deploy: the site had no route at all for bare `/` (only `/analyze/`, `/graph/<id>/`, etc.), and the explorer page's own logo hardcoded `href='/'` instead of reversing the URL name — both 404'd. Fixed: `/` now redirects to `/analyze/`, and the logo uses `reverse('analyze')`.

**Hosting note:** originally scoped for Railway (settings/Dockerfile were written host-agnostic on purpose, so this cost nothing) but deployed to Render instead — Railway's free trial is time/credit-limited ($5/30 days, then requires a paid plan to keep running), while Render's free tier has no time limit on the web service itself (only its free Postgres, which is deleted 90 days after creation — a known, accepted tradeoff for a low-stakes project, not yet worked around).

**Known limitation:** the analyze endpoint's rate limiter uses Django's default process-local cache (`LocMemCache`), so it's only correctly enforced with a single gunicorn worker/replica — which is the deployed default (no `--workers`/`WEB_CONCURRENCY` set). Scaling to multiple workers or replicas would split traffic across processes that don't share the counter, silently multiplying the effective limit. Would need a shared cache (Redis) to fix properly if that becomes real.

## What's next, in order

Nothing blocking is left for the MVP as originally scoped. Real remaining ideas, roughly in order of value:

1. **Work around Render's 90-day free Postgres expiry** — either recreate the DB and re-run analyses periodically, or move the analysis cache to something with a real persistence guarantee.
2. **Lazy-render containers** (packages/modules/classes), not just function-pill lists — the biggest remaining performance lever for very large repos.
3. **Private repo support** (GitHub OAuth) — explicitly out of scope for the MVP.
4. **Shared-cache rate limiting** (Redis) if this ever needs to scale beyond one worker/replica.
5. **More languages beyond the current ten** — additive per the `LanguageAnalyzer` registry (a grammar dependency + a `TreeSitterLanguageSpec` config table + fixtures), not a rewrite.

**Done this session:** multi-language parsing (Python + JavaScript/TypeScript/Go/Java/Rust/C/C++/Ruby/PHP/C#, via tree-sitter behind the `LanguageAnalyzer` interface — see `parsing/languages/`).

## Running it locally

```bash
venv\Scripts\Activate.ps1          # Windows
pip install -r requirements.txt
docker compose up -d db            # Postgres container
python manage.py migrate
set DJANGO_DEBUG=True              # required now that DEBUG defaults to False
python manage.py runserver
```
Or the whole stack via `docker compose up --build` (it already sets `DJANGO_DEBUG=True`).

## Git workflow / conventions in use

- Branch off `dev` (the default branch); `master` is production, kept in sync by fast-forwarding it to `dev` on request — not automatic, and not every commit.
- **Commits and PRs now include attribution** (`Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>` on commits, a "Generated with Claude Code" footer on PR descriptions) — this is a live, current instruction from the project owner that **supersedes** the earlier "no attribution" convention this file used to document.
- **No Jira/ticket references anywhere** in commits, branches, or PR descriptions — the project moved off ticket-based tracking; this file (and `canopy-dev-notes.md`) is the source of truth for status instead.
- Batch related work into one PR rather than one PR per small step.
- Every PR gets reviewed by hand (no `/code-review` skill, no subagents) before merging — a standing instruction for this project specifically.
- If stacking branches for related work, be careful with `gh pr merge --delete-branch` run back-to-back across a deep stack — it can race GitHub's base-branch retargeting and auto-close PRs whose base branch just got deleted. If that happens: verify no content was lost with `git diff --stat` between the stray branch and `dev` before deleting anything, then merge the stack's tip directly into `dev` with a plain `git merge`.

## Environment notes (Windows-specific gotchas hit during setup)

- VS Code's integrated terminal caches `PATH` at process launch — installing something new (Docker Desktop, `gh` CLI) won't be visible until VS Code is **fully quit and reopened**, not just "Reload Window" or a new terminal tab.
- Docker Desktop now installs per-user at `C:\Users\<user>\AppData\Local\Programs\DockerDesktop\`, not the old machine-wide `C:\Program Files\Docker\`.
- `gh` CLI is installed and authenticated (`gh auth status` to verify) — used for PR creation/management throughout.
