# Onboarder Cloud — the org space

A standalone, multi-tenant web app on top of the Onboarder analysis engine.

An **org owner** connects their repositories once. The app clones them, runs the
exact same static analysis the IDE plugins ship, and links everything into one
shared map — services, pages, screens, database tables and shared models, with
the real calls **between** repositories drawn in. Anyone on the team can then
**walk into the org space** and click any star to see what a thing is, where it
lives (`file:line`), and what it talks to.

It reuses the engine wholesale — not a fork. `cloud/server` puts `backend/` on
the path and drives `detect_projects → analyze → link_workspace` into one
workspace per org, then serves the existing map UI pointed at that workspace.

```
cloud/
  server/
    __init__.py   bootstrap: wire in backend/app, use cloud/data for storage
    main.py       FastAPI app — engine routers + org API + landing + map viewer
    orgs.py       org / repo / scan endpoints (owner-key protected)
    orgdb.py      org + org_repos tables (alongside the engine's own schema)
    github.py     list an org/user's repos (stdlib; token used transiently)
    scan.py       clone each repo, analyze it, link the whole workspace
  web/
    index.html    the observatory — directory, create-space, owner console
  run.sh          start the server (uses backend/.venv)
```

## Run it

```bash
cd cloud && ./run.sh
```

Then open <http://127.0.0.1:8900>:

1. **Create an org space** — you get a one-time **owner key** (kept in your
   browser; copy it somewhere safe).
2. **Connect repositories** — paste a public `https` git URL, or import from a
   GitHub org/user (a token is only needed to see/clone private repos).
3. **Scan now** — repos are shallow-cloned, analyzed, and cross-linked. Progress
   streams into the console.
4. **Enter space** — the full Onboarder map, pinned to the org's workspace, for
   anyone to browse.

`PORT`, `HOST` and `ONBOARDER_DATA_DIR` are read from the environment.

## How it reuses the engine

| Step | Reused from `backend/app` |
| --- | --- |
| Find projects in a repo (incl. multi-module) | `analysis.ingest.detect_projects` |
| Build one project's graph | `analysis.runner.build_project_graph` |
| Persist nodes/edges | `analysis.graph.persist_analysis` |
| Cross-repo links (calls, shared tables, GraphQL, shared models) | `analysis.linker.link_workspace` |
| Serve the graph, node detail, trace, chat, flow report | `api.graph`, `api.chat`, … (mounted verbatim) |
| The map, layers, chat, export | the built `frontend/dist`, opened at `?ws=<org>` |

An org is just an engine **workspace** with an owner and a set of connected
repositories on top — so every capability the single-project tool has (grouping,
layer toggles, the chat, the flow-report export shipped alongside this) works in
the org space for free.

## Security notes

- **Owner key** is stored only as a SHA-256 hash; it is shown once and required
  (via `x-owner-key`) for every mutating action. Reading the directory and
  entering a space are open — that is the viewer experience.
- **GitHub tokens are never stored.** They are passed per request, used to list
  and to clone private repos, scrubbed from the clone's git config immediately,
  and never logged or returned.
- **Clone URLs are restricted** to public `https` hosts; loopback, private and
  link-local addresses are rejected (no SSRF into internal services).
- Analysis is **static** — source is read, never executed.

## Not yet (deliberately out of MVP scope)

Scheduled re-scans (a cron hitting `POST /api/orgs/{id}/scan` is all it needs),
real SSO/member management, and webhook-driven incremental rescan on push. The
seams for each are called out in `scan.py` / `orgs.py`.
