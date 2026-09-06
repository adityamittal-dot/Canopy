# Canopy

**Live at [canopy-v7hb.onrender.com](https://canopy-v7hb.onrender.com/)**

Paste a GitHub repo link in. Canopy builds a hierarchical, explorable diagram of the codebase: repo → top-level modules/packages → files → classes → functions. Functions are the leaf nodes — the actual building blocks. Clicking any node shows what job it's responsible for, its source code, and its callers/callees.

Think "Obsidian's graph view, but auto-generated from a codebase instead of hand-written notes," combined with the backlinks idea: a function's callers/callees matter just as much as its position in the file tree.

## Why

Existing tools stop short of this combination:

- **GitDiagram** — LLM-generated Mermaid diagrams, not structurally accurate.
- **DeepWiki** — full wiki-style explanation + chat, not an explorable structural graph.
- **Sourcetrail** (unmaintained since 2021) — the closest structural blueprint, but abandoned.
- **Swimm**, **CodeSee** (defunct) — similar auto-generated maps, no longer around.

None of them drill all the way down to individual functions as leaf nodes, and none combine "explore the hierarchy" with "understand exactly the node you're looking at" in one seamless interaction. That's the gap Canopy fills.

## How it works

1. **Ingest** — shallow `git clone --depth 1` of the given repo URL into a temp folder; walk every `.py` file.
2. **Parse** — `ast.parse()` each file; extract modules, classes, functions/methods (including nested), docstrings, and line ranges.
3. **Call graph** — walk each function body for `ast.Call` nodes, resolve them against a repo-wide symbol table (same file first, then repo-wide). Unresolved/dynamic calls are marked external/unknown rather than guessed.
4. **Metrics** — lines of code, rough cyclomatic complexity, and fan-in/fan-out per function.
5. **Persist** — the parsed graph (nodes + edges as JSON) is cached in Postgres, keyed by repo URL + commit hash.
6. **Render** — a nested box/pill tree (repo → packages → modules → classes → functions), collapsed past the function level by default. Clicking a node opens a side panel with its docstring, source snippet (syntax-highlighted, fetched live from GitHub), metrics, and clickable callers/callees. Toggles show/hide call edges, tests, and vendored dependencies; a search bar jumps straight to any qualified name.

## Tech stack

- **Web framework:** Django, with `django-plotly-dash` embedding a Dash app directly inside Django views/templates — one Python codebase, no separate frontend build.
- **Interactive graph:** a hand-rolled Dash tree renderer (no Cytoscape/D3) — plain `html.Div`/`html.Button` components styled with a custom CSS design system (OKLCH color tokens, JetBrains Mono/IBM Plex Mono), plus one clientside (pure-JS, no server round-trip) callback for instant node-selection highlighting.
- **Parser:** Python's built-in `ast` module (Python-only for the MVP, no external dependencies).
- **Storage:** PostgreSQL via Django's ORM — `Repo` / `CommitAnalysis` models, with a `JSONField` holding the parsed graph. Doubles as the analysis cache.
- **Hosting:** Render (Docker-based web service + managed Postgres), WhiteNoise for static files, gzip compression.
- **No LLM, no chat, no background job queue for v1** — static analysis only, kept fast, deterministic, and infra-light.

## Key decisions

| Decision | Why |
|---|---|
| No LLM / no chat for v1 | Keeps the core product free, fast, deterministic, infra-light. |
| Static analysis over LLM-guessed structure | More accurate than asking an LLM to infer architecture — avoids hallucinated relationships. |
| Python-only MVP | The built-in `ast` module needs zero extra dependencies. |
| Dash (not React) | Keeps the whole build in one Python codebase — a hand-rolled component tree instead of a graph-visualization library, once the UI moved to a nested box/pill layout traced from a reference design rather than a force-directed graph. |
| Django, via `django-plotly-dash` | Django owns routing/models/auth/admin; Dash owns the interactive graph. |
| PostgreSQL over SQLite | Production-realistic setup, better concurrent-write handling, and stronger native JSON support/indexing for the parsed graph data. |
| No background job queue for MVP | Parsing is fast without an LLM in the loop, so it runs synchronously in a Django view. |

## Getting started

```bash
# clone and enter the repo
git clone https://github.com/adityamittal-dot/Canopy.git
cd Canopy

# create and activate a virtualenv
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # macOS/Linux

# install dependencies
pip install -r requirements.txt

# start Postgres (via Docker) and run migrations
docker compose up -d db
python manage.py migrate

# run the dev server
python manage.py runserver
```

Or run the whole stack (app + database) via Docker:

```bash
docker compose up --build
```

### Deploying it yourself

The app is Docker-based and reads all production config from environment variables — see `.env.example` for the full list (`SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DATABASE_URL`, optional `GITHUB_TOKEN`, etc.). It's currently deployed on [Render](https://render.com) (a Docker web service + their managed Postgres plugin), but nothing about it is Render-specific — the same image runs anywhere that can build a `Dockerfile` and inject env vars (Railway, Fly.io, a plain VM).

## Known limitations (accepted for v1)

- Dynamic Python features (decorators, `getattr`, metaclasses) can defeat static call resolution — marked as unknown rather than guessed.
- No private repo support yet (would need GitHub OAuth).
- Python-only — no support yet for other languages.
- Runs as a single Django app/process; the per-IP rate limit on the analyze endpoint uses Django's process-local cache, so it only holds correctly with a single gunicorn worker/replica (the deployed default).

## Roadmap

- **Phase 1 — Parsing engine:** clone, walk, AST extraction, call graph, metrics. No Django yet — pure Python, validated against a real mid-size repo. ✅ Done.
- **Phase 2 — Django app + visualization:** wrap the parser in Django, persist via the ORM, render the first interactive graph with a node detail panel. ✅ Done.
- **Phase 3 — Exploration experience:** cross-cutting "who calls this" view, search by name, noise filtering (tests/vendor, default hidden), graceful large-repo handling. ✅ Done.
- **Phase 4 — Polish, deploy, buffer:** UI redesign (traced from a reference design, full custom CSS system), performance work (clientside selection highlighting, gzip), production hardening, deployment. ✅ Done — live on Render.
- **Not yet started:** multi-language support beyond Python, private repo support (GitHub OAuth), lazy-rendering containers for very large repos (currently only function lists collapse by default; packages/modules/classes always render in full).
