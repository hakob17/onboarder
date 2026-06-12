# onboarder frontend

React + Vite + TypeScript implementation of the Claude Design handoff
(`Onboarder.html` connected prototype). Wired to the live backend — no mock data.

## Run

```sh
# terminal 1 — backend (port 8000)
cd backend && uv run uvicorn app.main:app --port 8000

# terminal 2 — frontend (port 5173, proxies /api → :8000)
cd frontend && npm install && npm run dev
```

To enable AI cards, chat, and guided tours, either paste your Anthropic API key in
**Settings** (gear icon — validated and stored backend-side) or set
`ANTHROPIC_API_KEY` in the backend's environment. The **Tour** button in the top bar
generates (or replays) an AI walkthrough whose steps drive the map highlights.

## Screens (from the design)

| Screen | Implementation |
|---|---|
| Upload & analysis | Multi-zip drop zone → creates a workspace, uploads each zip; stepper + live log driven by the `/events` SSE stream; recents from `GET /workspaces` |
| System map | Five barycenter-ordered columns (endpoints → tables); curved hairline edges; dashed = low-confidence, dotted teal = cross-project/outbound; zoom + minimap; topbar search highlights matches |
| Trace | Click an endpoint → `GET /trace` → animated flow highlight, rest dimmed |
| Table view | Star layout (services → repositories → table) with red/green writes/reads; panel with writer/reader chains, `file:line` evidence links (click → inline code peek), columns with PK |
| Service detail | AI summary card (lazy `POST /enrich`, cached), tokenized source viewer with evidence lines highlighted, in/out dependency lists, legend |
| Chat | Docked panel over the dimmed map; real streaming from `POST /chat`; `[node:id]` citations render as clickable chips; `focus_view` tool calls drive the map live; activity line from tool events |

## Structure

```
src/
├── styles.css        design tokens + components (ported from the handoff, fluid shell)
├── icons.tsx         line icon set from the design
├── api.ts            REST client + SSE/fetch-stream parsing
├── model.ts          backend graph → design node model + column layout
├── App.tsx           phases (home / analyzing / workspace), views, selection, highlights
└── components/
    ├── shell.tsx     rail + topbar
    ├── NodeCard.tsx  layer-tinted node cards, method chips, project chips
    ├── MapGraph.tsx  layered map, edges, zoom, minimap
    ├── StarGraph.tsx table-centric star with reads/writes coloring
    ├── panels.tsx    table panel, node panel, AI card, evidence code peek
    ├── CodeViewer.tsx lightweight tokenizer + line highlights
    ├── Chat.tsx      streaming chat, node chips, ui directives
    └── Upload.tsx    drop zone, recents, analysis stepper + log
```

Design-prototype chrome that was intentionally **not** carried over: the bottom
route-nav and the tweaks panel (the chosen defaults are baked in: curved edges,
stacked AI card, docked chat, teal accent). The bundle's `upload.jsx` was missing,
so the upload screen was reconstructed from the bundle's CSS, the chat transcript,
and the v1 `app/screen-upload.jsx`.
