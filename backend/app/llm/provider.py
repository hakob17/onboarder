"""AI backend abstraction: route model calls to the Anthropic API (stored/env key)
or the local `claude` CLI (no key — uses the user's Claude subscription).

Which one is chosen by config.ai_provider(). Both a one-shot structured call
(structured) and a plain text call (text) are provided; features use these
instead of talking to the Anthropic SDK directly.
"""
import json
import re
import subprocess

from ..config import MODEL, ai_provider, claude_cli_path

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of a CLI response (tolerates prose / code fences)."""
    for candidate in _fence_or_braces(text):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise ValueError("no JSON object found in model output")


def _fence_or_braces(text: str):
    m = _FENCE_RE.search(text)
    if m:
        yield m.group(1).strip()
    # first {...} balanced span
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    yield text[start:i + 1]
                    break
        start = text.find("{", start + 1)
        if start > 20000:
            break


def _run_claude(prompt: str, timeout: int = 240) -> str:
    exe = claude_cli_path()
    if not exe:
        raise RuntimeError("claude CLI not found — install it or select the Anthropic key provider")
    r = subprocess.run(
        [exe, "-p", prompt, "--output-format", "json"],
        capture_output=True, text=True, timeout=timeout,
    )
    env = None
    try:
        env = json.loads(r.stdout)
    except json.JSONDecodeError:
        pass
    if isinstance(env, dict):
        if env.get("is_error"):
            # e.g. "Failed to authenticate: OAuth session expired" — surface it verbatim
            raise RuntimeError(f"claude CLI: {env.get('result') or env.get('error') or 'error'}")
        text = env.get("result") or env.get("text")
        if text is not None:
            return text
    if r.returncode != 0:
        raise RuntimeError(f"claude CLI failed ({r.returncode}): {(r.stderr or r.stdout)[:300]}")
    return r.stdout


def structured(prompt: str, model_cls):
    """One-shot structured completion validated into model_cls (a pydantic model)."""
    prov = ai_provider()
    if prov == "claude-cli":
        schema = json.dumps(model_cls.model_json_schema())
        full = (prompt + "\n\nRespond with ONLY a single JSON object — no prose, no markdown — "
                "that matches this JSON schema:\n" + schema)
        return model_cls.model_validate(_extract_json(_run_claude(full)))
    from . import get_client
    resp = get_client().messages.parse(
        model=MODEL, max_tokens=8192,
        messages=[{"role": "user", "content": prompt}], output_format=model_cls,
    )
    return resp.parsed_output


def text(prompt: str, system: str | None = None, max_tokens: int = 8192) -> str:
    """One-shot plain-text completion."""
    prov = ai_provider()
    if prov == "claude-cli":
        full = f"{system}\n\n{prompt}" if system else prompt
        return _run_claude(full)
    from . import get_client
    kwargs = {"model": MODEL, "max_tokens": max_tokens,
              "messages": [{"role": "user", "content": prompt}]}
    if system:
        kwargs["system"] = system
    resp = get_client().messages.create(**kwargs)
    return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
