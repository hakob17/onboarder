# Onboarder — Design Document

**One-liner:** Upload one or more project zips — any language, backend or mobile — and get an interactive map of the whole system: entry points → logic → data access → databases, plus the calls *between* projects. An AI guide answers questions in plain language and drives the visualization.

---

## 1. The problem & the model we're encoding

Real developers onboard by **tracing**: pick an entry point (an API endpoint, a screen), follow the call chain down through services to repositories and the database — or start from a table and work upward ("who writes to `orders`?"). In a microservice or app+backend world the trace crosses project boundaries: a mobile screen calls service A, which calls service B, which writes a table that service C reads.

Onboarder makes both directions — and the cross-project hops — a single click, and adds an LLM that explains the *business meaning* of what the graph shows.

**Personas**
- **New developer** — traces flows end-to-end (across services), reads generated "business logic cards" instead of cold code, jumps to source when needed.
- **Manager / PM / QA** — asks "what happens when a user places an order?" and gets an answer plus a highlighted path. Never reads code.

**Core interactions**
1. **Trace an entry point** — click `POST /api/orders` (or a mobile screen) → the full path lights up, across layers *and across projects*, down to the tables it touches.
2. **Table-centric view** — click the `orders` table → writers in red, readers in green, **aggregated across every project in the workspace** — including the case where two services quietly share one table.
3. **Business logic cards** — click any service/module → an LLM-written card: purpose, key business rules, side effects, gotchas — with links to the exact lines of evidence.
4. **Chat that drives the map** — "where do we charge the customer's card?" → answer cites graph nodes; the assistant simultaneously focuses/highlights the relevant subgraph, even when the answer spans two services.
5. **System view** — projects as boxes, edges between them (HTTP/gRPC calls, queues, shared databases). The 10,000-ft map a new joiner needs on day one.

---

## 2. Requirements that shape everything

**R1 — Any project type.** Node.js, Python, Go, Java, PHP, Ruby, C#, mobile (Android/Kotlin, iOS/Swift, React Native, Flutter)… The tool must produce a *useful* map for anything, and a *deep* map for popular stacks. → Solved by the three-tier extraction strategy (§5).

**R2 — Multi-project workspaces.** A user uploads two (or N) zips of different projects where one calls another. The graph must capture cross-project edges: HTTP/gRPC calls, queue producer→consumer pairs, and shared databases. → Solved by the workspace model + linker (§6). **The data model is workspace-first from day one**, even while the UI ships single-project features first — retrofitting multi-project onto a single-project schema is the expensive mistake to avoid.

---

## 3. Architecture

```
┌──────────────────────┐   REST + SSE   ┌──────────────────────────────┐
│  Browser (React SPA) │◄──────────────►│   FastAPI backend (Python)   │
│  • system view       │                │  • workspaces / uploads      │
│  • React Flow graph  │                │  • graph API • chat agent    │
│  • node panel • chat │                └───┬──────────┬──────────┬────┘
└──────────────────────┘                    │          │          │
                                 per-project│ workspace│          │
                                 ┌──────────▼───┐  ┌───▼────────┐ │
                                 │ Analysis     │  │ Linker     │ │
                                 │ pipeline     │  │ cross-proj │ │
                                 │ (3 tiers §5) │  │ edges (§6) │ │
                                 └──────┬───────┘  └───┬────────┘ │
                                        │              │     Anthropic API
                                 SQLite (per workspace)│     • LLM extraction
                                 graph • cross edges • │     • enrichment cards
                                 summaries • overrides │     • link adjudication
                                                       │     • chat agent
```

**Key design decision: hybrid static + LLM analysis.**
- **Static analysis builds the skeleton** wherever it can (deterministic, cheap, never hallucinates an edge).
- **The LLM fills the gaps static analysis can't reach**: unknown frameworks, dynamic languages, business-meaning summaries, ambiguous link adjudication, and chat. Every LLM-extracted fact is validated against the source (cited line spans must exist) before it enters the graph.

**Evidence-first principle:** every edge — including cross-project links — carries evidence (`file`, `line`, snippet, and for links: the matching config/contract). The UI always answers "why does this edge exist?". Trust is the product.

---

## 4. The graph model (language-neutral)

Layers are **concepts**, not framework names. Every ecosystem maps onto them:

| Concept | Spring | NestJS / Express | Django / FastAPI | Go (gin/echo/net·http) | Laravel | Mobile (Android/iOS/RN/Flutter) |
|---|---|---|---|---|---|---|
| **Entry points** | `@RestController` methods | `@Get()` / `app.get()` | `urls.py` / `@app.get` | route registrations | `routes/*.php` | screens / activities / view controllers |
| **Logic** | `@Service` | services / providers | services / views | packages / funcs | services / actions | view models / blocs / stores |
| **Data access** | `JpaRepository` | Prisma / TypeORM / Sequelize | ORM models / queries | gorm / sqlx / database·sql | Eloquent | Room / CoreData / SQLite |
| **Data stores** | tables | tables | tables | tables | tables | local tables |
| **Outbound calls** | RestTemplate / WebClient / Feign | axios / fetch | requests / httpx | http.Client / gRPC | Guzzle | Retrofit / URLSession / dio / axios |
| **Async** | Kafka/Rabbit listeners | bull / kafka clients | celery | sarama / amqp | queues | push handlers |

### Nodes
`entry_point` (endpoint *or* screen), `logic` (service/module/view-model), `data_access` (repository/ORM model), `table`, `outbound_call` (HTTP/gRPC client call site), `queue` (topic), `external_api` (unmatched third party — Stripe, S3…), `project`.

Common fields: `id` (namespaced by project), `project_id`, `kind`, `name`, `qualified_name`, `file`, `line_start/end`, `summary` (LLM card, lazy), `metadata`, `confidence`.

### Edges
Within a project: `HANDLES`, `CALLS`, `USES`, `MAPS_TO`, `READS`, `WRITES`, `MAKES_CALL` (logic → outbound_call), `PUBLISHES`, `CONSUMES`.
Across projects (workspace-level): `CALLS_SERVICE` (outbound_call → entry_point), `PUBLISHES`/`CONSUMES` through a shared `queue` node, and shared-`table` convergence (two projects' edges pointing at one table node).

Every edge: `confidence` (0–1) + `evidence: [{file, line, snippet}]`. Low-confidence edges render dashed.

The layered UI adapts per project type: a backend shows *Entry points | Logic | Data access | Tables | Outbound*; a mobile app shows *Screens | Logic | Outbound calls (+ local store)* — its outbound column is what links it to the backends.

---

## 5. Extraction strategy — three tiers (how "any project" is honest)

**Tier A — Deep extractors (precision, per framework).** Hand-written, deterministic, high-confidence. Shipped incrementally: Spring first, then NestJS/Express, FastAPI/Django, Go HTTP routers, Laravel, Retrofit (Android), URLSession/Alamofire (iOS). Each is a plugin implementing one interface: `detect(files) -> bool`, `extract(symbols) -> nodes+edges`.

**Tier B — Generic tree-sitter core (works for everything).** tree-sitter has grammars for Java, Kotlin, Swift, Dart, JS/TS, Python, Go, PHP, Ruby, C#… One universal pass produces: files, classes/functions, imports, a heuristic intra-project call graph, and **candidate sites** — string literals that look like routes (`"/api/orders/:id"`), SQL (`SELECT … FROM orders`), URLs (`${ORDERS_URL}/api/…`), and HTTP-client usage. Tier B alone already yields a navigable map for any codebase.

**Tier C — LLM-assisted extraction (the universal fallback).** For projects with no Tier A extractor — or to fill Tier A/B gaps — the candidate sites from Tier B are batched to the LLM with structured outputs:

```python
class ExtractedFacts(BaseModel):
    endpoints: list[Endpoint]        # method, path, handler symbol, line
    outbound_calls: list[Outbound]   # method, url_template, base_url_var, line
    queries: list[Query]             # tables, operation (read/write), line
    queue_ops: list[QueueOp]         # topic, produce/consume, line
```

Guardrails: only candidate files (not the whole repo) go to the model; every fact must cite a line span that actually exists and parses (validated before insertion, else dropped); results cached by file content hash; bulk runs go through the Batch API (50% off). This is what makes "upload anything" honest without writing fifty extractors — while Tier A keeps popular stacks precise and nearly free.

**Pipeline per project:** safe unzip (zip-slip/bomb guards, never execute code) → stack detection (build manifests + annotation scan; **a monorepo with several build manifests auto-splits into multiple projects**) → Tier B → Tier A if matched → Tier C for gaps → config & contract harvest (`.env`, `application.yml`, `settings.py`, `docker-compose.yml`, k8s manifests, OpenAPI specs, `.proto` files, migrations) → persist. Progress streams over SSE.

---

## 6. Workspaces & cross-project linking

**Workspace** = a named collection of uploaded projects ("acme system"). Projects can be added at any time; each addition re-runs the linker.

### The linker
Matches Project A's `outbound_call` nodes to Project B's `entry_point` nodes, and wires queues and shared tables. Signals, strongest first:

1. **Contracts** — shared `.proto` files (gRPC) and OpenAPI specs: near-certain matches.
2. **Config resolution** — resolve base URLs through env vars and config (`ORDERS_API_URL=http://orders-service`), docker-compose service names, k8s Service manifests → ties a call site to a *specific* project.
3. **Path-template matching** — normalize `/api/orders/{id}` vs `/api/orders/:id` vs `` `/api/orders/${orderId}` `` → method + path similarity score.
4. **Queue topology** — producer topic name == consumer topic name → `PUBLISHES`/`CONSUMES` through a shared queue node.
5. **Shared databases** — same database identity (from config) + same table name across projects → edges converge on one shared table node. The UI badges it **"shared table — written by 2 projects"**; this is exactly the kind of architectural landmine onboarding should surface.

**LLM adjudication for the ambiguous middle:** when signals conflict or are weak, the call site + candidate endpoints + config evidence go to the model for a structured verdict + confidence. **Humans get the final word:** every inferred link can be confirmed or rejected in the UI; overrides persist in the workspace (`status: inferred | confirmed | rejected`). Unmatched outbound calls become `external_api` nodes — the third-party dependency map falls out for free.

### System view
Projects as containers; cross-project edges between them (HTTP/gRPC, queues, shared DBs). Click an edge → evidence pair (call site ↔ endpoint, or producer ↔ consumer). Traces cross boundaries: *mobile `CheckoutScreen` → `POST /api/orders` in orders-service → `billing-service` → `payments` table.* Drill into any project → its layered view. The table view aggregates readers/writers across all projects.

---

## 7. LLM integration (Anthropic API)

Verified against current docs (June 2026). Official `anthropic` Python SDK.

| Use | Model | Pricing (in/out per MTok) |
|---|---|---|
| Chat, Tier C extraction, link adjudication, cards (default) | `claude-opus-4-8` | $5 / $25 |
| Cost lever for bulk passes (user-selectable) | `claude-sonnet-4-6` ($3/$15) or `claude-haiku-4-5` ($1/$5) | |

Cost reality: enriching a 300-class service ≈ $6 on Opus 4.8 (~$3 via Batch API). Tier C extraction is bounded by candidate-file count, not repo size. A model picker + per-workspace token budget meter keep large repos predictable.

### Business logic cards
- `client.messages.parse(..., output_format=ServiceCard)` (Pydantic structured outputs): `purpose`, `business_rules`, `side_effects`, `gotchas`.
- Bulk pass over the top-N classes by graph centrality via the **Batch API**; everything else enriched lazily on first click; cached by file content hash (re-uploads only re-summarize changed files).
- Language-agnostic by construction — the input is source text plus graph context.

### Chat agent (grounded, tool-using, workspace-scoped)
Manual tool-use loop server-side (`client.messages.stream`, `thinking={"type": "adaptive"}`), streamed to the browser over SSE.

| Tool | Purpose |
|---|---|
| `list_projects()` | workspace inventory |
| `query_graph(project?, kind?, name_contains?)` | find nodes (cross-project) |
| `get_node(node_id)` | details + edges + evidence + card |
| `trace_paths(from_id, to_id?)` | paths — **crosses project boundaries** |
| `read_source(project, file, start, end)` | ground truth |
| `search_code(project?, pattern)` | ripgrep over extracted sources |
| `focus_view(node_ids, mode)` | **UI directive** — highlight/isolate/trace in the graph |

`focus_view` is the differentiator: answers manipulate the visualization. SSE events: `text_delta`, `tool_started`, `ui_directive`, `done`. Answers must cite node ids → rendered as clickable chips.

**Prompt caching:** frozen system prompt (instructions + workspace overview: projects, stacks, counts, top flows) with `cache_control: {"type": "ephemeral"}` on the last system block; conversation grows after the breakpoint (~0.1× on cache reads). No timestamps/UUIDs in the prefix.

**Hallucination guardrails:** tools-only grounding; claims require node/evidence citations; optional secret-redaction pass before source text leaves the machine.

---

## 8. Frontend

React 18 + Vite + TS, SSE via `EventSource`/fetch streams. Graph renderer, barycenter column layout, code viewer, and styling are bespoke — ported from the Claude Design handoff (`Onboarder.html`): design tokens in `frontend/src/styles.css`, Space Grotesk + JetBrains Mono, light/dark themes.

**Views**
1. **System view** — project containers + cross-project edges (HTTP, queue, shared-DB). Entry view for multi-project workspaces.
2. **Project map** — layered DAG, columns adapt to project type (backend vs mobile), collapsible by package/domain, search + filters.
3. **Trace** — endpoint/screen selected → full path highlighted across projects, rest dimmed.
4. **Table view** — table-centric star: writers red, readers green, grouped by project; "shared table" badge.
5. **Node panel** — card, in/out edges with evidence links, source with span highlighted; for cross-project links: confirm / reject buttons.
6. **Chat dock** — streaming answers, node chips, live `focus_view` directives.

---

## 9. API surface

```
POST   /workspaces                                → {workspace_id}
POST   /workspaces/{id}/projects     (zip upload, repeatable)
GET    /workspaces/{id}/events       SSE: analysis + linker progress
GET    /workspaces/{id}/graph        ?view=system | project=<pid> | table=<tid>
GET    /workspaces/{id}/nodes/{nid}  details; triggers lazy enrichment
POST   /workspaces/{id}/links/{lid}  {status: confirmed | rejected}
GET    /workspaces/{id}/source       ?project=&file=&start=&end=
POST   /workspaces/{id}/chat         SSE: text_delta | tool_started | ui_directive | done
DELETE /workspaces/{id}              wipes files + DB
```

**Storage (single SQLite file, workspace-scoped rows):** `workspaces`, `projects`, `files`, `symbols`, `candidates`, `nodes(project_id, …)`, `edges(project_id, …)`, `cross_edges(workspace_id, src, dst, kind, confidence, evidence, status)`, `summaries(content_hash → card)`, `events`, `chat_messages`. Path queries via recursive CTEs; no graph DB needed at this scale. Per-workspace DB files are a later option if isolation demands it.

---

## 10. Security & operational

- Uploaded code is **never executed** — parsing only. Zip-slip + bomb guards, size caps, per-workspace isolation, full wipe on delete.
- LLM cost guardrails: candidate-file gating for Tier C, lazy enrichment, hash caches, Batch API, per-workspace budget meter, model picker.
- Local-first: `docker compose up`; the only external dependency is the Anthropic API.

---

## 11. Build plan

**Phase 0 — Skeleton (workspace-shaped from day one).** FastAPI + React scaffold; workspace/project data model; upload → safe unzip → stack detection → file tree. *Done when: two zips upload into one workspace and both file trees render.*

**Phase 1 — Graph UX + first deep extractor.** Tier A Spring extractor end-to-end: layered map, node panel with source + evidence, trace mode, table view (red/green). No LLM. *Done when: `spring-petclinic` traces from endpoint to table with zero LLM calls.*

**Phase 2 — Universal engine (R1 lands).** Tier B generic core for all tree-sitter languages + Tier C LLM extraction with validation, candidate gating, Batch API; mobile outbound-call extraction (Retrofit/URLSession/dio); adaptive columns. *Done when: a Node/Express app, a Go service, and a Flutter app each produce a useful layered map with evidence.*

**Phase 3 — Business logic cards.** Centrality-ranked batch pass + lazy on-click enrichment + hash cache.

**Phase 4 — Chat.** Workspace-scoped agent loop, SSE streaming, node-chip citations, `focus_view`. *Done when: "who writes to the orders table?" answers correctly and highlights the writers.*

**Phase 5 — Cross-project linking (R2 lands).** Config/contract harvest → linker (signals 1–5) → LLM adjudication → system view, cross-boundary traces, confirm/reject UI, shared-table badges, external-API nodes. *Done when: a 2-service + mobile-app workspace shows mobile → service A → service B → shared table, with evidence on every hop.*

**Phase 6 — Depth & breadth.** More Tier A extractors (NestJS, Django, Go, Laravel), migrations as authoritative schema, transaction boundaries, auto-generated guided tours, upload diffing ("what changed since last release?"), shareable read-only links.

**Phase 7 — Baselines & visual diff.** Node ids are deterministic, so a diff is a set
comparison. `snapshots(id, workspace_id, label, git_ref, created_at, graph JSON)` captured
three ways: manual "Save baseline", an automatic rolling pre-re-analysis snapshot (the
save-watcher flow gets diffs for free), and git-ref baselines for local repos
(`git archive <ref>` → temp dir → dry-run pipeline, never touching the checkout).
`GET /workspaces/{id}/diff?from&to` → added/removed nodes by id, added/removed edges by
(src,dst,kind), changed nodes by meaningful-metadata hash (columns, handler — not line
drift). UI: an explicit compare mode rendering the union graph — added = green ring/+,
removed = ghosted dashed, changed = amber dot, with a grouped "What changed" panel
(mode banner notes that diff mode repurposes red/green from writes/reads, git-style).
VS Code: after save-triggered re-analysis, toast "N changes vs baseline" → diff overlay.
AI tie-in: a `get_diff` chat tool — "explain what changed", or verify a stated expectation
("placeOrder should now publish to SNS") against the diff.

**Phase 8 — Infrastructure layer (IaC-aware architecture view).** An infra repo is just
another project with its own extractor. Detect `*.tf` → stack `terraform`; parse with
python-hcl2: ECS services/task definitions (images, env vars), Lambdas (handler, env),
SQS/SNS (+ subscriptions, event source mappings), RDS/DynamoDB/S3/ElastiCache, API
Gateway/ALB. New node kinds `infra_compute`, `topic`, `datastore`, `gateway` — every node
and edge with `.tf file:line` evidence. Binding infra ↔ app repos reuses linker machinery
(new cross-edge kinds `DEPLOYED_AS`, `PUBLISHES_TO`, `SUBSCRIBES_TO`, `USES_STORE`):
image/ECR names vs project tokens, task-def env vars vs harvested app config keys (also
feeds the HTTP linker authoritative hostnames), Lambda handler paths vs repo files —
confidence-scored, confirm/reject. v2: code-side corroboration (`@SqsListener`,
`sns.publish`, boto3 queue names) joins the code graph to the infra graph end-to-end.
UI: an "Architecture" rail view — deployable units as containers (click → drill into that
repo's code map), queues/topics/stores as distinct shapes. Known limits: HCL interpolation
(resolve var defaults, else token-match around `${…}`), local modules only,
CloudFormation/serverless.yml next, CDK requires synthesized output.

Phases 4 and 5 can swap if cross-project linking is the higher priority — nothing in 5 depends on 4.

---

## 12. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Call-graph precision in dynamic languages (Python/JS/PHP) | Tier B heuristics + Tier C LLM with line-validated output; confidence rendering; evidence always visible |
| Cross-project false links | Signal hierarchy (contracts > config > path similarity); LLM adjudication; human confirm/reject persisted; dashed low-confidence rendering |
| DI/dynamic dispatch in static languages | Framework conventions cover ~95%; multi-impl → low-confidence edges; LLM adjudicates on demand |
| Huge repos / monorepos | tree-sitter is fast (ms/file); monorepo auto-split into projects; candidate gating bounds LLM cost; incremental re-parse by hash later |
| LLM hallucination | extraction: line-span validation; chat: tools-only grounding + mandatory citations |
| Weird projects (no framework at all) | graceful degradation: Tier B map (packages, call graph, SQL/URL string finds) + file browser + chat over source |

---

## 13. Repo layout

```
onboarder/
├── DESIGN.md
├── docker-compose.yml
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── analysis/
│   │   │   ├── ingest.py          # unzip, guards, stack detection, monorepo split
│   │   │   ├── generic.py         # Tier B: tree-sitter symbols, candidates
│   │   │   ├── extractors/        # Tier A plugins: spring.py, express.py, retrofit.py, …
│   │   │   ├── llm_extract.py     # Tier C: structured extraction + validation
│   │   │   ├── configs.py         # env/yaml/compose/k8s/openapi/proto harvest
│   │   │   ├── linker.py          # cross-project matching (signals 1–5)
│   │   │   ├── sql.py             # sqlglot tables + read/write
│   │   │   └── graph.py           # build + SQLite persistence
│   │   ├── llm/
│   │   │   ├── enrich.py          # cards: parse() + Batch API + hash cache
│   │   │   ├── chat_agent.py      # streaming tool-use loop
│   │   │   └── tools.py           # graph tools + focus_view directive
│   │   └── api/                   # routers: workspaces, graph, links, chat (SSE)
│   └── pyproject.toml
└── frontend/
    └── src/
        ├── views/                 # System, Map, Trace, Table, NodePanel, Chat
        ├── graph/                 # React Flow + elk, edge styling, project containers
        └── api/
```
