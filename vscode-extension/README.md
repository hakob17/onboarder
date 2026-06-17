# Onboarder — VS Code extension

Maps the folder(s) you have open in VS Code **in place** — no zip upload. The
extension spawns the Onboarder backend as a local sidecar, registers each
workspace folder as a project (multi-root workspaces become multi-project
graphs with cross-project links), and hosts the full Onboarder UI in a webview.
Evidence links (`OrderService.java:24`) open the real file in your editor at
that line.

## Run it (development)

```sh
# one-time: build the pieces the extension uses
cd frontend && npm install && npm run build
cd ../backend && uv sync
cd ../vscode-extension && npm install && npm run compile
```

Open `vscode-extension/` in VS Code and press **F5** ("Run Onboarder
Extension"). In the dev host window, open any project folder and run
**Onboarder: Map this workspace** (or click the status-bar item).

## Commands

| Command | What it does |
|---|---|
| `Onboarder: Map this workspace` | Analyze open folder(s), open the map panel |
| `Onboarder: Re-analyze workspace` | Re-run analysis (e.g. after pulling changes) |
| `Onboarder: Set Anthropic API key` | Validate + store a key for AI summaries / chat / tours |

## Live features

- **Save → re-analyze**: saving a file re-analyzes its project (debounced) and the
  open map refreshes in place — selection preserved. Toggle with
  `onboarder.autoReanalyze`.
- **CodeLens**: above mapped code units — endpoints get `▷ trace POST /api/orders`,
  controllers `N routes · show in map`, services `in/out counts`, entities
  `N writers · M readers`. Clicking selects the node in the map panel.

## Packaging

`npm run package` compiles, bundles the built frontend into `media/dist`, and
produces `onboarder-<version>.vsix` (installable via "Extensions: Install from
VSIX…"). The Python backend is still required on the machine (`uv` + the
`backend/` folder, or point `onboarder.backendUrl` at a running instance);
bundling it as a standalone binary (PyInstaller) is future work.

## Local vs remote backend

The extension needs a backend. It picks one in this order: `onboarder.backendUrl`
setting → baked-in `DEFAULT_BACKEND_URL` → a local sidecar it spawns from
`onboarder.backendPath`.

- **Local backend** (empty `backendUrl`): analyzes the open folder **in place** — no
  upload. Full experience: live save-reanalyze, evidence links and the Infra tab's
  "open handler" jump to the real file. Requires the backend on the machine
  (a clone of this repo + `uv`, or `backendPath` set).
- **Remote backend** (e.g. a Railway URL in `backendUrl`): the extension **zips the
  open folder and uploads it** for analysis (it can't ask a remote server to read
  your disk). Map / Trace / Tables / Infra / Chat all work; files still open locally.
  Re-analysis is on the **Re-analyze** command (not auto-on-save). `.env` files are
  excluded from the upload. Best when you don't want to run a backend locally.

If you see *"not a directory …"* or *"no backend to use"*, it means no backend was
reachable — set `onboarder.backendUrl` to your hosted URL, or `onboarder.backendPath`
to a local backend clone.

## Settings

| Setting | Default | Purpose |
|---|---|---|
| `onboarder.backendUrl` | *(empty)* | Attach to an already-running backend instead of spawning one |
| `onboarder.backendPath` | `../backend` next to the extension | Where the backend lives (needs `uv`) |
| `onboarder.frontendDist` | `../frontend/dist` next to the extension | Built SPA the webview hosts |
| `onboarder.startCommand` | `uv run uvicorn app.main:app --port ${port}` | How to start the sidecar |

## Notes

- Analysis is fully local; only the small scoped slices sent for AI summaries /
  chat leave the machine (and only once a key is configured).
- The webview talks to the sidecar over `127.0.0.1` on a per-session free port.
- Zip-upload workspaces from the web UI still work — both frontends share the
  same backend.
