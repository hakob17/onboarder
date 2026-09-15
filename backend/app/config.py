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


def claude_cli_path() -> str | None:
    """Path to the local `claude` (Claude Code) CLI, if available — used for key-free AI."""
    import shutil

    from .db import get_setting
    configured = get_setting("claude_cli_path")
    if configured and Path(configured).exists():
        return configured
    found = shutil.which("claude")
    if found:
        return found
    for c in ("/opt/homebrew/bin/claude", "/usr/local/bin/claude",
              str(Path.home() / ".local/bin/claude"), str(Path.home() / ".claude/local/claude")):
        if Path(c).exists():
            return c
    return None


def ai_provider() -> str:
    """Effective AI backend: 'anthropic' (API key), 'claude-cli' (local CLI), or 'none'.

    The stored 'ai_provider' setting selects it; 'auto' (default) prefers a key, then the CLI.
    """
    from .db import get_setting
    choice = get_setting("ai_provider") or "auto"
    have_key = key_source() != "none"
    have_cli = claude_cli_path() is not None
    if choice == "anthropic":
        return "anthropic" if have_key else "none"
    if choice == "claude-cli":
        return "claude-cli" if have_cli else "none"
    if have_key:
        return "anthropic"
    if have_cli:
        return "claude-cli"
    return "none"


def llm_enabled() -> bool:
    return ai_provider() != "none"
