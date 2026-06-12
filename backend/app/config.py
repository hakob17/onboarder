import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("ONBOARDER_DATA_DIR", str(Path(__file__).resolve().parent.parent / "data")))
DB_PATH = DATA_DIR / "onboarder.db"

MAX_ZIP_MB = int(os.environ.get("ONBOARDER_MAX_ZIP_MB", "200"))
MAX_UNCOMPRESSED_MB = int(os.environ.get("ONBOARDER_MAX_UNCOMPRESSED_MB", "1000"))
MAX_FILE_MB = int(os.environ.get("ONBOARDER_MAX_FILE_MB", "20"))
MAX_FILES = int(os.environ.get("ONBOARDER_MAX_FILES", "60000"))

STATIC_DIR = os.environ.get("ONBOARDER_STATIC_DIR", "")
MODEL = os.environ.get("ONBOARDER_MODEL", "claude-opus-4-8")
ENRICH_MAX_SOURCE_LINES = int(os.environ.get("ONBOARDER_ENRICH_MAX_SOURCE_LINES", "400"))
CHAT_MAX_TOKENS = int(os.environ.get("ONBOARDER_CHAT_MAX_TOKENS", "16000"))
CHAT_MAX_TOOL_ROUNDS = int(os.environ.get("ONBOARDER_CHAT_MAX_TOOL_ROUNDS", "12"))

def resolve_root(root_path: str) -> Path:
    """Project roots are DATA_DIR-relative for zip uploads, absolute for local folders."""
    p = Path(root_path)
    return p if p.is_absolute() else DATA_DIR / root_path


def get_api_key() -> str | None:
    """Stored (Settings UI) key wins; falls back to the environment."""
    from .db import get_setting
    stored = get_setting("anthropic_api_key")
    if stored:
        return stored
    return os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")


def key_source() -> str:
    from .db import get_setting
    if get_setting("anthropic_api_key"):
        return "stored"
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return "env"
    return "none"


def llm_enabled() -> bool:
    return key_source() != "none"
