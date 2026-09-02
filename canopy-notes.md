# Canopy — Project Notes (updated: PostgreSQL)

_Last updated: 2026-09-01_

## The idea

Paste a GitHub repo link in. The app builds a hierarchical, explorable diagram of the codebase: repo -> top-level modules/packages -> files -> classes -> functions. Functions are the leaf nodes — the actual building blocks. Clicking any node shows what job it's responsible for, its source code, and its callers/callees.

Think "Obsidian's graph view, but auto-generated from a codebase instead of hand-written notes," combined with the backlinks idea: a function's callers/callees matter just as much as its position in the file tree.

## Competitive landscape

- **GitDiagram** — paste a repo, get an interactive Mermaid diagram; clicking a box opens the real file on GitHub. Mostly LLM-driven (feeds file tree + README to a model to invent the diagram structure, then validates it).
- **DeepWiki** (Cognition/Devin) — generates a full wiki-style explanation of a repo plus a chat interface.
- **Sourcetrail** (open-sourced, unmaintained since 2021) — the closest structural blueprint: interactive, explorable dependency graph of classes/functions/calls, built entirely from compiler-based indexers. No AI at all.
- **Swimm**, **CodeSee** (now defunct) — similar auto-generated codebase maps.

**The gap we're filling:** none of these drill all the way down to individual functions as leaf nodes, and none combine "explore the hierarchy" with "understand exactly the node you're looking at" as one seamless interaction.

## Key decisions

| Decision | Why |
|---|---|
| No LLM / no chat for v1 | Keeps the core product free, fast, deterministic, infra-light. Chat needs an LLM to be good; without one it's just search/navigation — deferred rather than shipped weak. |
| Static analysis over LLM-guessed structure | More accurate than asking an LLM to infer architecture from file tree/README, which can hallucinate relationships. |
| Python-only MVP | Python's built-in `ast` module needs zero extra dependencies — fastest path to a working prototype. |
| Dash + dash-cytoscape for the graph UI (not React) | Keeps the whole build in Python. `dash-cytoscape` wraps Cytoscape.js and supports the hierarchical layouts + click callbacks needed. |
| Django as the web framework, via `django-plotly-dash` | Embeds the Dash/dash-cytoscape graph inside a real Django app — Django owns routing/models/auth/admin, Dash owns the interactive graph. Django's ORM/admin gives a working data layer almost for free. |
| Django ORM (PostgreSQL) instead of a flat-file cache | Natural place to store `Repo`/`CommitAnalysis` rows keyed by commit hash — doubles as the cache. Postgres over SQLite for a more production-realistic setup and better native JSON field support/indexing for the parsed graph data. |
| No background job queue / Redis for MVP | Parsing is fast without an LLM in the loop, so it runs synchronously inside a Django view. Revisit only if usage demands async processing. |

## Tech stack

- **Web framework:** Django, with `django-plotly-dash` embedding a Dash app directly inside Django views/templates. One Python codebase, no separate frontend build, no CORS.
- **Interactive graph:** `dash-cytoscape` (wraps Cytoscape.js) inside the embedded Dash app — hierarchical/dagre-style layouts, Python callbacks for click-to-inspect and expand/collapse.
- **Parser:** Python's built-in `ast` module (Python-only for the MVP).
- **Storage:** PostgreSQL, accessed via Django's ORM (`psycopg2`/`psycopg`) — `Repo` / `CommitAnalysis` models, JSON field for the parsed graph.
- **No LLM, no chat, no background job queue for MVP.**

## Pipeline

1. **Ingest:** shallow `git clone --depth 1` from the given repo URL into a temp folder; walk every `.py` file.
2. **Parse:** `ast.parse()` each file; walk the tree to extract modules, classes, functions/methods (incl. nested), docstrings (`ast.get_docstring()`), and line ranges.
3. **Call graph:** walk each function body for `ast.Call` nodes, resolve calls to other indexed functions (same file first, then repo-wide). Unresolved/dynamic calls marked external/unknown.
4. **Metrics:** lines of code + rough cyclomatic complexity (branching node count) per function, plus fan-in/fan-out (caller/callee counts).
5. **Persist:** save the parsed graph (nodes + edges as JSON) to a Django `CommitAnalysis` row, keyed by repo URL + commit hash — acts as the cache.
6. **Serve:** a Django view triggers analysis (or serves a cached `CommitAnalysis`); the embedded Dash app reads that row's JSON.
7. **Render:** `dash-cytoscape` renders the tree, collapsed by default past depth 2. Node click -> side panel (docstring, source snippet, LOC/complexity, clickable callers/callees). Toggle for the cross-cutting "who calls this, anywhere in the repo" view.

## Forward-compatibility

Parser sits behind a small interface (e.g. `LanguageAnalyzer` class with `parse(file) -> nodes, edges`) rather than wired directly into Django views, so adding another language later is additive, not a rewrite.

## Known limitations (accepted for v1)

- Dynamic Python features (decorators, `getattr`, metaclasses) defeat static call resolution sometimes — mark as unknown, don't chase 100% accuracy.
- No private repo support yet (would need GitHub OAuth) — deferred.
- Large repos need default filtering (skip `tests/`, `venv/`, `__pycache__`, vendored deps) and deep collapse-by-default.
- Everything runs as one Django app/process for the MVP — fine at solo-project scale.

## Execution plan (2–4 weeks)

### Week 1 — Parsing engine
- [ ] Project setup, venv, repo clone function, `.py` file walker
- [ ] AST extraction: modules, classes, functions, docstrings, line ranges, imports; handle decorators/lambdas/async/nested functions
- [ ] Call graph: resolve `ast.Call` nodes via a repo-wide symbol table; mark unresolved as external
- [ ] Metrics: LOC, cyclomatic complexity, fan-in/fan-out
- [ ] Validate against a real mid-size open-source Python repo

### Week 2 — Django app + basic visualization
- [ ] Django project + app, `django-plotly-dash` installed and configured
- [ ] `Repo` / `CommitAnalysis` models + migrations
- [ ] View: accepts repo URL, runs clone+parse, saves analysis, checks cache first
- [ ] Register Dash app, wire up `dash-cytoscape`, hierarchical layout, collapse/expand
- [ ] Node detail side panel via Dash callback: docstring, snippet, metrics, callers/callees, GitHub link

### Week 3 — Exploration experience
- [ ] Cross-cutting "who calls this" toggle view
- [ ] Search by function/class name
- [ ] Filter controls (tests/vendor/pycache/venv)
- [ ] Graceful handling of large repos, loading states, error messages
- [ ] End-to-end test on 2–3 real repos

### Week 4 — Polish, deploy, buffer
- [ ] UI polish, README
- [ ] Deploy Django app (Railway/Render/Fly.io) with Gunicorn + WhiteNoise
- [ ] Rate limiting/usage guard
- [ ] Real-world testing on unfamiliar repos, fix issues, gather feedback

## Open questions (revisit post-MVP)

- Multi-language expansion: tree-sitter vs. per-language LSP servers — which first?
- LLM layer, if/when added: bolt on for explain/chat only, fed by extracted docstrings + call graph, never foundational.
- Private repos: GitHub OAuth, deferred until public-repo support is solid.
- Large monorepos: may need smarter chunking/pagination beyond default filtering + collapse.
- Call resolution accuracy: how much effort to sink into resolving dynamic Python patterns before diminishing returns.
- Async processing: revisit if a hosted version gets real traffic and the synchronous Django view becomes a bottleneck.

## Links

- Notion project hub: (private page, see Claude conversation for link)
