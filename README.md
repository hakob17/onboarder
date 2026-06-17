# Onboarder

Understand an unfamiliar codebase in minutes. Onboarder statically analyzes one
or more projects — uploaded as zips or read in place — and renders an
interactive architecture map (endpoints → controllers → services →
repositories → tables), with an AI layer that explains, investigates, and
drives the map. Built for developers onboarding and for non-technical
teammates (PMs, QA, managers) who need to see how the system works without
reading code.

## How it works

1. **Analyze** — code is parsed (never executed) in three tiers: deep
   framework extractors (Spring), a generic tree-sitter pass for any language
   (Express/NestJS, FastAPI/Flask, Go, Retrofit, SQL strings), and an optional
   LLM pass for stacks the first two miss. Migration `.sql` files are the
   authoritative table schema.
2. **Graph** — everything becomes nodes and edges in SQLite, and **every edge
   carries evidence** (`file:line` + snippet), so the UI can always answer
   "why does this edge exist?".
3. **AI on top** — a tool-using agent works against the graph and source:
   scoped summaries, multi-round investigations, guided tours. It can only
   cite what it actually read.

## Features

| Feature | How it works |
|---|---|
| **System map** | Layered columns (Endpoints · Controllers · Services · Repositories · Tables), curved hairline edges, layer hues, zoom + minimap, search-to-highlight, light/dark. Columns adapt to whatever layers a stack actually has. |
| **Trace a flow** | Click an endpoint → its full downstream path lights up (animated), everything else dims. |
| **Table view** | Click a table → star layout with **red = writes, green = reads**, writer/reader chains with `file:line` evidence, column list (from entities, overridden by migrations), shared-table badge. |
| **Evidence everywhere** | Every claim links to `file:line`; clicking shows the code (web) or opens the real file in your editor (VS Code). |
| **AI summary cards** | Per endpoint/service/repository, generated **only from that unit's lines** (an endpoint card sends ~4 lines, and the card header says exactly which: "Generated from OrderController.java:14–17 · 4 lines only"). Cached by content hash. |
| **Chat: explain & investigate** | Ask "how does order placing work?" or "opening an order takes 10s — where should I look?". The agent does real round trips — find endpoints → trace → read each hop's source → rank "places to look" with citations — and highlights what it discusses on the map. Honest about what it could not verify. |
| **Guided tours** | One click generates a 5–7 step narrated walkthrough (validated against real node ids); each step drives the map. |
| **Infrastructure awareness (Terraform / SAM)** | `*.tf` and SAM/CloudFormation templates become graph nodes: Lambdas/ECS as compute (with runtime + handler), SQS/SNS, RDS/Dynamo/S3, API gateways. SAM `Api` events and API-Gateway routes become real endpoints, SNS subscriptions and event-source mappings become edges, and each compute node is bound (`RUNS`) to the code module that implements its handler — all with `.tf`/template `file:line` evidence. |
| **Multi-project workspaces** | Drop several zips (or open a multi-root VS Code workspace): a linker matches outbound HTTP calls to other projects' endpoints (env-var resolution, normalized path templates, service-name identity), flags **shared database tables**, and renders dotted cross-project edges. Links are confidence-scored, evidence-backed, and human-confirmable. |
| **Export & share** | Export the current view as an **SVG** (vector, for docs/slides) or the workspace graph as **JSON** (a portable, committable artifact). In the extension it saves via a file dialog; in the browser it downloads. |
| **Persona views** | A topbar toggle — **Developer / Manager / Power** — adjusts detail: Manager shows a high-confidence business view (hides low-confidence/inferred noise), Power surfaces per-node confidence, Developer is the balanced default. |
| **Live refresh** | Saving a file (VS Code) or re-analyzing re-runs the affected project; any open map updates in place via server-sent events. |
| **Bring your own API key** | Paste a key in Settings (validated with a free token-count call before storing) — AI features switch on instantly. Or set `ANTHROPIC_API_KEY` on the backend. |
| **VS Code / Antigravity extension** | Maps the open folder(s) **without any upload**: status-bar launcher, `Onboarder: Ask about this codebase`, CodeLens above mapped code ("2 routes · show in map", "1 writers · 4 readers"), evidence links open files at the line, save-triggered re-analysis. Ships as a `.vsix`. |
| **Privacy & safety** | Analysis is local and static — uploaded/opened code is never executed. Only the small scoped slices for AI features leave the machine, and only once a key is configured. Zip-slip/zip-bomb guards on uploads. |

## Run

```sh
# backend (FastAPI, Python 3.12 via uv)
cd backend && uv run uvicorn app.main:app --port 8000

# web UI (Vite + React)
cd frontend && npm install && npm run dev   # http://localhost:5173

# VS Code extension
cd vscode-extension && npm install && npm run package   # → onboarder-0.1.0.vsix
```

Details: [backend/README.md](backend/README.md) ·
[frontend/README.md](frontend/README.md) ·
[vscode-extension/README.md](vscode-extension/README.md) ·
design: [DESIGN.md](DESIGN.md)
