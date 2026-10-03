# Phase 2C. One-call VLM assessment for citizen photo tips.
#
# Contract: assess_photo(photo_path, claim_text, sar_context) -> dict with
#   {status: 'supports'|'contradicts'|'inconclusive',
#    description: str,
#    model: str|None,
#    assessed_at: ISO-8601 str}
#
# Rules (D-029):
#   - OPENROUTER_API_KEY -> OpenRouter, model thinkingmachines/inkling:free.
#     Status/text from model.
#   - No key: inconclusive, model=None.
#   - 10s timeout per call; any exception -> inconclusive (safe default).
#   - Never raise. The bot must accept a tip even when no model is callable.
#
# Provider history (D-037): Gemini 2.5 Flash and Groq qwen were both removed.
# Groq remains the TEXT-LLM provider for /api/brief; image VLM is OpenRouter
# only. inkling:free was verified via OpenRouter's public /api/v1/models to
# declare `image` among its input modalities, and it costs nothing, which
# matters for a demo that may be photographed a dozen times.
#
# This module does NOT touch the signal schema, the disk layout, or HTTP.
# It is a pure helper for bot/tipline.py to call. The audit drawer reads the
# output via the vlm_assessment block written by the bot's credibility layer.
#
# Network calls use only urllib from stdlib so the module stays dependency-free
# for the demo machine. If a richer client is ever wanted (backoff, retries),
# do it behind these functions so the bot never imports it.
"""
Photo-channel VLM hook. Returns a 3-way verdict the credibility layer can
modulate trust on, without ever overriding spatial tiering.

Reads OPENROUTER_API_KEY from the environment only.
"""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any


# Hard cap so a slow model never blocks the bot. The bot also wraps this in
# its own shorter timeout at the call site; this is the final backstop.
# Browser-like User-Agent. Default `Python-urllib/x.y` UA gets a 403-1010 from
# Cloudflare-fronted hosts on Windows. A Chrome UA passes the fingerprint check.
# D-033. OpenRouter sits behind the same kind of edge, so keep it.
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0 Safari/537.36"
)

TIMEOUT_S = 10.0

# The single image-VLM provider. Kept as a list so the call site stays a loop:
# adding a second provider later must not mean rewriting assess_photo().
PROVIDERS: tuple[dict[str, str], ...] = (
    {
        "name": "openrouter",
        "env_key": "OPENROUTER_API_KEY",
        # Verified present in OpenRouter's public /api/v1/models listing, with
        # `image` among its declared input modalities. Free tier.
        "model_id": "thinkingmachines/inkling:free",
        # OpenAI-compatible, same wire format as the Groq endpoint.
        "endpoint": "https://openrouter.ai/api/v1/chat/completions",
    },
)


PROMPT_VERSION = "vlm-photo-v1"


def _now_iso() -> str:
    """ISO-8601 in UTC, second precision. Matches the schema's date-time shape."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _inconclusive(model: str | None, description: str) -> dict[str, Any]:
    """Build the safe-default response. Single point so any failure path
    converges on the same shape and the schema validator stays happy.

    Note: shape matches verification.vlm_assessment in signal.schema.json --
    NO additional keys here or the schema's additionalProperties: false
    will reject it.
    """
    return {
        "status": "inconclusive",
        "model": model,
        "description": description,
        "assessed_at": _now_iso(),
    }


def _classify(raw_text: str) -> str:
    """Map a model's free-form reply to one of our three statuses.

    We ask the model to return JSON; if it returns plain text, try to recover
    a one-word verdict. Anything unclear becomes inconclusive.
    """
    text = (raw_text or "").strip()
    if not text:
        return "inconclusive"

    # Try JSON first. Strip ```json fences if the model wrapped its answer.
    cleaned = text
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].lstrip()
    # Strip <think>...</think> blocks (Qwen emits them in plain text on the
    # wire even though the user is not in a chat UI). The verdict and JSON
    # almost always appear AFTER the think block, so we keep everything after
    # the last </think>. D-033.
    import re as _re
    cleaned = _re.sub(r"<think>.*?</think>", "", cleaned, flags=_re.DOTALL).strip()
    try:
        obj = json.loads(cleaned)
        verdict = str(obj.get("status", "")).strip().lower()
        if verdict in {"supports", "contradicts", "inconclusive"}:
            return verdict
        # Some models return a boolean field instead.
        if "consistent" in obj:
            return "supports" if bool(obj["consistent"]) else "contradicts"
    except json.JSONDecodeError:
        pass

    # Plain-text fallback.
    low = text.lower()
    if "contradicts" in low or "inconsistent" in low or "inconsistent" in text.lower():
        return "contradicts"
    if "supports" in low or "consistent" in low:
        return "supports"
    if "inconclusive" in low or "cannot tell" in low or "unclear" in low:
        return "inconclusive"
    # Last resort: any positive word with no negative near it -> supports.
    return "inconclusive"


def _read_photo(photo_path: str) -> tuple[bytes, str] | dict[str, Any]:
    """Read the file off disk. Returns (bytes, mime) on success, or an
    inconclusive dict on any failure. Lives here so the network code never
    has to know about the filesystem."""
    # photo_path is public-relative (console/public/data/tips/...); resolve
    # to project root so the bot's cwd doesn't matter.
    if not photo_path:
        return _inconclusive(
            None, "no photo path supplied; VLM not invoked"
        )
    # Find repo root: this file is at <root>/bot/vlm_check.py.
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(here)
    # photo_path starts with 'tips/' (per the photo_path pattern in the schema).
    candidates = [
        os.path.join(repo_root, "console", "public", "data", photo_path),
        os.path.join(repo_root, photo_path),
    ]
    for full in candidates:
        if os.path.isfile(full):
            with open(full, "rb") as fh:
                data = fh.read()
            # Cheap mime guess by extension -- sufficient for the two APIs we use.
            ext = os.path.splitext(full)[1].lower()
            mime = "image/jpeg" if ext in {".jpg", ".jpeg"} else f"image/{ext.lstrip('.') or 'octet-stream'}"
            return data, mime
    return _inconclusive(
        None, f"photo not found on disk at {photo_path}; treating as inconclusive"
    )


def _build_prompt(claim_text: str, sar_context: dict[str, Any]) -> str:
    """Construct the prompt we send to whichever model wins.

    The instruction is the same for both providers: produce a 3-way verdict in
    a single sentence and a status word. We do NOT ask for a tier or a score
    -- the credibility layer in the bot owns those decisions.
    """
    ctx_parts: list[str] = []
    cells = sar_context.get("cells") or []
    if cells:
        ctx_parts.append(
            "SAR-derived context (this is what our satellite assessment says "
            f"about the area): {json.dumps(cells, separators=(',', ':'))}"
        )
    note = sar_context.get("note")
    if note:
        ctx_parts.append(f"Notes: {note}")

    sar_blurb = "\n".join(ctx_parts) if ctx_parts else "No SAR context available."

    return (
        "You are a disaster-report photo triage assistant. A citizen sent the "
        "attached photo with this claim:\n\n"
        f"CLAIM: {claim_text or '(no caption)'}\n\n"
        f"{sar_blurb}\n\n"
        "Look at the photo. Decide ONE of three verdicts:\n"
        "  supports     -- the photo's content is consistent with the claim.\n"
        "  contradicts  -- the photo's content rules the claim out.\n"
        "  inconclusive -- you cannot tell (blurry, off-topic, unrelated scene).\n\n"
        "Return STRICT JSON on a single line with two fields and nothing else:\n"
        '{"status": "<supports|contradicts|inconclusive>", "description": "<one sentence, <= 30 words>"}\n'
        "Do not include any other text. Do not include code fences."
    )


def _call_openai_compatible(
    prov: dict[str, str], photo_bytes: bytes, mime: str, prompt: str
) -> str:
    """Hit an OpenAI-compatible /chat/completions endpoint with an inline image.

    Used for OpenRouter. Returns the raw model text; raises on any HTTP/JSON
    error and lets the caller convert that to inconclusive.
    """
    api_key = os.environ[prov["env_key"]]
    url = prov["endpoint"]
    data_url = f"data:{mime};base64,{base64.b64encode(photo_bytes).decode('ascii')}"

    body = {
        "model": prov["model_id"],
        "temperature": 0.0,
        "max_tokens": 256,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": _BROWSER_UA,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    choices = payload.get("choices", [])
    if not choices:
        return ""
    return choices[0].get("message", {}).get("content", "")


def assess_photo(
    photo_path: str,
    claim_text: str,
    sar_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Top-level entry. Returns a schema-shaped verdict dict.

    `sar_context` is opaque to the model -- the bot assembles whatever it
    has (cell id, nearby damaged counts, brief note) into a small dict and
    forwards it here. We refuse to spawn a network call if the file isn't on
    disk, so a stale `media_refs` row never blocks the bot.
    """
    sar_context = sar_context or {}

    # 1. Missing path or file -- bail before any provider.
    file_or_status = _read_photo(photo_path)
    if isinstance(file_or_status, dict):
        return file_or_status  # already inconclusive
    photo_bytes, mime = file_or_status

    # 2. Pick a provider. First key wins; no key -> inconclusive.
    prompt = _build_prompt(claim_text, sar_context)
    for prov in PROVIDERS:
        if not os.environ.get(prov["env_key"]):
            continue
        try:
            raw = _call_openai_compatible(prov, photo_bytes, mime, prompt)
            status = _classify(raw)
            description = ""
            # Try to extract the description if the model returned JSON.
            cleaned = raw.strip().strip("`")
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:].lstrip()
            try:
                obj = json.loads(cleaned)
                description = str(obj.get("description", "")).strip()[:500]
            except json.JSONDecodeError:
                description = raw.strip()[:500]
            return {
                "status": status,
                "model": prov["model_id"],
                "description": description or "(no description returned)",
                "assessed_at": _now_iso(),
            }
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, KeyError):
            # Any failure on a configured provider falls through to the next
            # one; if it's the last one, we exit the loop and return inconclusive.
            continue
        except Exception:
            # Catch-all so the bot never crashes on a malformed response.
            continue

    # No key, or every configured provider failed.
    return _inconclusive(
        None,
        "no VLM provider available (set OPENROUTER_API_KEY); "
        "credibility layer treats this as no-modulation",
    )


if __name__ == "__main__":
    # Smoke: call with a missing file and confirm the inconclusive path.
    out = assess_photo("tips/does-not-exist.jpg", "demo")
    print(json.dumps(out, indent=2))
