def get_client():
    """Anthropic client honoring the Settings-stored key, then the environment."""
    import anthropic

    from ..db import get_setting

    stored = get_setting("anthropic_api_key")
    if stored:
        return anthropic.Anthropic(api_key=stored)
    return anthropic.Anthropic()
