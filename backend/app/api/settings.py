from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import MODEL, key_source, llm_enabled
from ..db import delete_setting, get_setting, set_setting

router = APIRouter(tags=["settings"])


def _masked(key: str | None) -> str | None:
    if not key:
        return None
    return f"{key[:10]}…{key[-4:]}" if len(key) > 18 else "…"


@router.get("/settings")
def get_settings() -> dict:
    return {
        "llm_enabled": llm_enabled(),
        "key_source": key_source(),
        "model": MODEL,
        "stored_key_preview": _masked(get_setting("anthropic_api_key")),
    }


class KeyUpdate(BaseModel):
    anthropic_api_key: str


@router.put("/settings/api-key")
def set_api_key(body: KeyUpdate) -> dict:
    key = body.anthropic_api_key.strip()
    if not key:
        raise HTTPException(400, "key is empty")

    import anthropic

    client = anthropic.Anthropic(api_key=key)
    try:
        client.messages.count_tokens(
            model=MODEL,
            messages=[{"role": "user", "content": "ping"}],
        )
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
        raise HTTPException(400, f"key rejected by the Anthropic API: {e.__class__.__name__}") from e
    except anthropic.APIConnectionError as e:
        raise HTTPException(502, "could not reach the Anthropic API to validate the key") from e
    except anthropic.APIStatusError as e:
        if e.status_code in (401, 403):
            raise HTTPException(400, "key rejected by the Anthropic API") from e
        # other statuses (rate limit, overloaded) mean the key authenticated

    set_setting("anthropic_api_key", key)
    return get_settings()


@router.delete("/settings/api-key")
def clear_api_key() -> dict:
    delete_setting("anthropic_api_key")
    return get_settings()
