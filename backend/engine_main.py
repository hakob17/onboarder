"""Frozen entrypoint for the bundled, self-contained Onboarder engine.

The VS Code / Antigravity extension launches this binary as a local sidecar
and talks to it over 127.0.0.1 — so analysis runs in place against the open
folder, with no zip upload and no Python/uv on the user's machine.

Port and data directory come from the environment:
  PORT               port to bind (default 8000)
  ONBOARDER_DATA_DIR writable dir for the SQLite db (extension passes globalStorage)

Uses the pure-Python asyncio/h11 stack (no uvloop/httptools/websockets) so the
frozen bundle stays small and free of extra native deps; local single-user
analysis doesn't need the C speedups.
"""
import os
import sys


def main() -> None:
    # MCP mode: speak the Model Context Protocol over stdio so an IDE's AI
    # assistant can call Onboarder's grounding tools. No HTTP server, no LLM key.
    if "--mcp" in sys.argv:
        from app.mcp_server import run as run_mcp
        run_mcp()
        return

    import uvicorn

    from app.main import app

    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "127.0.0.1")
    uvicorn.run(app, host=host, port=port, log_level="warning",
                loop="asyncio", http="h11", ws="none")


if __name__ == "__main__":
    main()
