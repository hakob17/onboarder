#!/usr/bin/env bash
# Build the self-contained Onboarder analysis engine for the current OS/arch.
# Output: dist/onboarder-engine/ (onedir) — the extension downloads + spawns it.
set -euo pipefail
cd "$(dirname "$0")"
rm -rf build dist onboarder-engine.spec

uv run --with pyinstaller pyinstaller --noconfirm --onedir --name onboarder-engine \
  --collect-all tree_sitter_language_pack \
  --collect-all tree_sitter \
  --collect-all hcl2 \
  --collect-all pydantic \
  --collect-all pydantic_core \
  --collect-submodules sqlglot \
  --collect-submodules app \
  --collect-all anthropic \
  --collect-submodules uvicorn \
  --hidden-import h11 \
  --hidden-import multipart \
  engine_main.py

echo "built: dist/onboarder-engine/"
