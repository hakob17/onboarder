# Deploying Onboarder

The repo ships a single-service container: a multi-stage [`Dockerfile`](Dockerfile)
builds the web UI and serves it from the FastAPI backend (same origin, no CORS or
URL config). [`railway.json`](railway.json) selects the Dockerfile builder and a
`/health` healthcheck, so Railway deploys it straight from a connected GitHub repo.

## Railway (GitHub-connected)

1. Push this repo to GitHub (private is fine).
2. Railway → **New Project → Deploy from GitHub repo** → pick this repo.
   Railway reads `railway.json`, builds the `Dockerfile`, and starts it.
3. Networking → **Generate Domain**. That URL serves both the UI and the API.
4. (Recommended) add a **Volume** mounted at `/data` so the SQLite store survives
   redeploys — `ONBOARDER_DATA_DIR` already points there.

Nothing else is required: the container binds `$PORT` automatically and serves the
built frontend from `ONBOARDER_STATIC_DIR` (baked into the image).

### Environment variables (all optional)

| Var | Default | Purpose |
|---|---|---|
| `PORT` | set by Railway | bind port (handled automatically) |
| `ONBOARDER_DATA_DIR` | `/data` | SQLite + working data (mount a volume here) |
| `ONBOARDER_STATIC_DIR` | `/app/web` | built UI served by the backend (set in the image) |
| `ANTHROPIC_API_KEY` | unset | operator-owned key enabling AI features for everyone hitting this deploy |
| `ONBOARDER_MODEL` | `claude-opus-4-8` | model id |
| `ONBOARDER_MAX_ZIP_MB` | `200` | upload cap |

> **Shared-deploy note.** AI keys are stored per-backend, not per-user. On a shared
> hosted instance either leave keys unset (AI features stay off until someone adds
> one in Settings — which then serves *everyone*), or set `ANTHROPIC_API_KEY` as an
> operator-owned env var and accept that you're paying for all usage. For
> per-developer keys, run the backend locally instead.

## What works on a hosted backend

A remote backend can read **uploaded zips**, not the developer's local disk — so the
hosted deploy is the **web app** (drag a `.zip`, get the map, chat, tours, diff).

The VS Code extension's *no-upload* local-folder analysis needs a backend that can
see your files, i.e. the local sidecar it spawns by default. To point the extension
at a hosted backend anyway, set `onboarder.backendUrl` (or bake `DEFAULT_BACKEND_URL`
in `vscode-extension/src/extension.ts`) — that gives zero-config, upload-mode usage.

## Local container (parity check)

```sh
docker build -t onboarder .
docker run -p 8080:8080 -e PORT=8080 onboarder
# open http://localhost:8080  → upload a .zip
```

## Other hosts

Any Docker host works (Fly.io, Render, Cloud Run, a VM): build the image, set a
persistent path for `ONBOARDER_DATA_DIR`, expose `$PORT`. `railway.json` is
Railway-specific and ignored elsewhere.
