#!/usr/bin/env bash
# Analyze a local project folder IN PLACE (no zip, no upload) and open the map.
#
#   ./onboarder-local.sh /path/to/your/project
#
# Starts the bundled engine locally, points it at the folder on disk, waits for
# analysis, and opens the browser straight to the mapped workspace.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
PROJECT="${1:-}"
if [ -z "$PROJECT" ] || [ ! -d "$PROJECT" ]; then
  echo "usage: $0 /path/to/project   (the folder to analyze)"; exit 1
fi
PROJECT="$(cd "$PROJECT" && pwd)"

ENGINE="$ROOT/backend/dist/onboarder-engine/onboarder-engine"
WEB="$ROOT/frontend/dist"
[ -x "$ENGINE" ] || { echo "engine not built — run: (cd backend && ./build_engine.sh)"; exit 1; }
[ -f "$WEB/index.html" ] || { echo "web UI not built — run: (cd frontend && npm install && npm run build)"; exit 1; }

PORT=$(python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1]);s.close()')
DATA="${ONBOARDER_DATA_DIR:-$HOME/.onboarder}"
mkdir -p "$DATA"
BASE="http://127.0.0.1:$PORT"

echo "▶ starting engine on $BASE  (data: $DATA)"
PORT="$PORT" HOST=127.0.0.1 ONBOARDER_DATA_DIR="$DATA" ONBOARDER_STATIC_DIR="$WEB" "$ENGINE" >"$DATA/engine.log" 2>&1 &
EPID=$!
trap 'echo; echo "stopping engine ($EPID)"; kill $EPID 2>/dev/null || true' INT TERM EXIT

for _ in $(seq 1 75); do sleep 0.4; curl -sf "$BASE/health" >/dev/null 2>&1 && break; done
curl -sf "$BASE/health" >/dev/null || { echo "✗ engine did not start — see $DATA/engine.log"; exit 1; }

NAME="$(basename "$PROJECT")"
WS=$(curl -s -X POST "$BASE/workspaces" -H 'content-type: application/json' \
      -d "{\"name\":$(python3 -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$NAME")}" \
      | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')

echo "▶ analyzing $PROJECT in place…"
curl -s -X POST "$BASE/workspaces/$WS/projects/local" -H 'content-type: application/json' \
     -d "{\"path\":$(python3 -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$PROJECT")}" >/dev/null

STATUS=""
for _ in $(seq 1 600); do
  sleep 1
  STATUS=$(curl -s "$BASE/workspaces/$WS/projects" \
    | python3 -c 'import sys,json;ps=json.load(sys.stdin);print(ps[0]["status"] if ps else "")' 2>/dev/null || echo "")
  case "$STATUS" in ready|failed) break;; esac
done

NODES=$(curl -s "$BASE/workspaces/$WS/graph" | python3 -c 'import sys,json;print(len(json.load(sys.stdin)["nodes"]))' 2>/dev/null || echo 0)
URL="$BASE/?api=&ws=$WS"
echo "▶ analysis $STATUS — $NODES nodes."
if [ "$NODES" = "0" ]; then
  echo "  (0 nodes — if this is unexpected, the stack may be unsupported; engine log: $DATA/engine.log)"
fi
echo "▶ opening $URL"
command -v open >/dev/null 2>&1 && open "$URL" || echo "  open this in your browser: $URL"
echo
echo "Engine is running (pid $EPID). Leave this terminal open; press Ctrl+C to stop."
wait $EPID
