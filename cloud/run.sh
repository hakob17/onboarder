#!/usr/bin/env bash
# Start the Onboarder Cloud (org-space) server.
# Reuses the engine's Python deps from backend/.venv and keeps its own data dir
# (cloud/data) so it never touches local-dev workspaces.
set -euo pipefail
cd "$(dirname "$0")"

PY="../backend/.venv/bin/python"
[ -x "$PY" ] || PY="python3"

export PORT="${PORT:-8900}"
export HOST="${HOST:-127.0.0.1}"

echo "Onboarder Cloud → http://$HOST:$PORT"
exec "$PY" -m uvicorn server.main:app --host "$HOST" --port "$PORT" "$@"
