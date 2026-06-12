# onboarder backend

FastAPI backend for onboarder (see ../DESIGN.md). Static analysis works with no API key.
LLM features (AI cards, chat, guided tours, Tier C extraction, link adjudication) activate
when a key is available — either paste one in the app's Settings (gear icon; validated via
a free `count_tokens` call and stored in the local DB, taking precedence) or set
`ANTHROPIC_API_KEY` in the backend environment.

## Run

```sh
cd backend
uv sync
ANTHROPIC_API_KEY=sk-... uv run uvicorn app.main:app --reload --port 8000
```

Interactive docs at http://localhost:8000/docs.

## Quick tour

```sh
# create a workspace, upload one or more project zips into it
WS=$(curl -s -X POST :8000/workspaces -H 'content-type: application/json' -d '{"name":"acme"}' | jq -r .id)
curl -s -X POST :8000/workspaces/$WS/projects -F file=@your-project.zip

# watch analysis progress (SSE)
curl -N :8000/workspaces/$WS/events

# the graph, a trace, a node with evidence
curl ":8000/workspaces/$WS/graph"
curl -G ":8000/workspaces/$WS/trace" --data-urlencode "from_id=<entry_point node id>"
curl ":8000/workspaces/$WS/nodes/<node id>"        # URL-encode the id

# LLM: business-logic card + grounded chat (needs ANTHROPIC_API_KEY)
curl -X POST ":8000/workspaces/$WS/nodes/<node id>/enrich"
curl -N -X POST ":8000/workspaces/$WS/chat" -H 'content-type: application/json' \
  -d '{"message":"who writes to the orders table?"}'
```

## Layout

```
app/
├── main.py               FastAPI app, CORS, /health
├── config.py             env-driven settings (ONBOARDER_*)
├── db.py                 SQLite schema + helpers (one file, workspace-scoped rows)
├── analysis/
│   ├── ingest.py         safe zip extraction, stack detection, monorepo split
│   ├── languages.py      tree-sitter parsers via tree-sitter-language-pack
│   ├── generic.py        Tier B: file/symbol index + candidate sites (routes/SQL/URLs)
│   ├── extractors/
│   │   └── spring.py     Tier A: endpoints, DI call graph, JPA tables, READ/WRITE
│   ├── sql_analysis.py   sqlglot table + operation extraction
│   ├── graph.py          persistence, node detail, recursive-CTE trace
│   └── runner.py         per-project background pipeline + progress events
├── llm/
│   ├── tools.py          chat agent tools (graph queries, source, focus_view)
│   ├── enrich.py         business-logic cards (structured outputs, hash cache)
│   └── chat_agent.py     streaming tool-use loop, prompt caching, SSE
└── api/                  routers: workspaces, projects, graph, chat
```

## Notes

- Uploaded code is never executed — parsing only. Zip-slip/zip-bomb guards in `ingest.py`.
- Caps via env: `ONBOARDER_MAX_ZIP_MB` (200), `ONBOARDER_MAX_UNCOMPRESSED_MB` (1000),
  `ONBOARDER_MAX_FILES` (60000). Model via `ONBOARDER_MODEL` (default `claude-opus-4-8`).
- Test fixtures in `tests/fixtures/` (Spring, two Express apps, Android/Retrofit, monorepo zip).
- Extraction tiers: Spring (deep), `extractors/generic_web.py` (Express/NestJS,
  FastAPI/Flask, Go, Retrofit — routes, SQL tables, outbound calls), and
  `llm_extract.py` (Tier C catch-all, runs only with an API key when the
  deterministic tiers found no entry points).
- Migration files are authoritative for schema: `CREATE TABLE` statements found in
  `.sql` files override entity/query-derived columns and add migration-only tables
  (`analysis/migrations.py`).
- AI guided tours: `POST /workspaces/{id}/tours` generates a validated, node-grounded
  walkthrough (the frontend's Tour button plays it); `GET` lists existing tours.
- Settings API: `GET /settings`, `PUT /settings/api-key` (validates before storing),
  `DELETE /settings/api-key`. Projects can be removed via
  `DELETE /workspaces/{id}/projects/{pid}`.
- Cross-project linking (DESIGN.md §6) runs automatically after each analysis and
  via `POST /workspaces/{id}/link`: outbound URL templates are resolved through
  harvested env/config values and matched to other projects' endpoints
  (method + normalized path + host/service identity); same-named tables across
  projects become SHARED_TABLE links. Links are reviewable —
  `POST /workspaces/{id}/links/{link_id}` with confirmed/rejected survives re-runs.
