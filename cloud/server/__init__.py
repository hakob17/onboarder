"""Onboarder Cloud — the standalone, multi-tenant "org space".

This package reuses the existing single-workspace analysis engine that lives in
``backend/app`` without copying a line of it. Importing this package wires that
engine in:

  * ``backend/`` is put on ``sys.path`` so ``import app.analysis...`` resolves to
    the exact same extractors, linker, graph and chat the IDE plugins ship;
  * ``ONBOARDER_DATA_DIR`` is pointed at ``cloud/data`` so the hosted product
    keeps its own SQLite database, fully separate from local-dev data.

Both are set here, at package import, *before* any submodule runs its own
``from app... import`` — so ``app.config`` reads the right data dir the first
time it is imported.
"""
import os
import sys
from pathlib import Path

_CLOUD_ROOT = Path(__file__).resolve().parent.parent          # …/onboarder/cloud
_BACKEND = _CLOUD_ROOT.parent / "backend"                      # …/onboarder/backend

if _BACKEND.is_dir() and str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

# Give the hosted product its own data directory (db + cloned repos) unless the
# operator has already chosen one. setdefault so a real deploy can override it.
os.environ.setdefault("ONBOARDER_DATA_DIR", str(_CLOUD_ROOT / "data"))

CLOUD_ROOT = _CLOUD_ROOT
BACKEND_ROOT = _BACKEND
REPO_ROOT = _CLOUD_ROOT.parent
DATA_DIR = Path(os.environ["ONBOARDER_DATA_DIR"])
REPOS_DIR = DATA_DIR / "repos"
