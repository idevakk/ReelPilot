"""Script generation via an OpenAI-compatible chat-completions endpoint.

Falls back to a small templated generator if no API key is set, so the
pipeline still works offline (assumes the user has cached B-roll + music).
"""

from __future__ import annotations

import json
import random
from typing import Any

from pydantic import ValidationError

from .config import Settings
from .models import Beat, Script

SYSTEM_PROMPT = (
    "You are a viral short-form video script writer for TikTok/Shorts/Reels. "
    "Write punchy 25-35 second scripts in a hook -> body -> CTA structure. "
    "Each beat must include 2-4 short b-roll search keywords that describe the visual."
)

USER_TEMPLATE = """Write a short-form video script about this topic:

Topic: {topic}
Hook clip: {hook_name} ({hook_desc})

IMPORTANT: Do NOT think, reason, or explain. Output ONLY the raw JSON object below and nothing else.

Return strict JSON only with this shape:
{{
  "beats": [
    {{"role": "hook_intro", "narration": "<=15 words, punchy", "broll_keywords": ["k1","k2"], "target_seconds": 3.0}},
    {{"role": "body", "narration": "...", "broll_keywords": ["..."], "target_seconds": 5.0}},
    {{"role": "body", "narration": "...", "broll_keywords": ["..."], "target_seconds": 5.0}},
    {{"role": "body", "narration": "...", "broll_keywords": ["..."], "target_seconds": 5.0}},
    {{"role": "cta", "narration": "follow for more", "broll_keywords": ["subscribe","like"], "target_seconds": 3.0}}
  ]
}}

Constraints:
- Total target_seconds roughly 25-35.
- First beat must reference the hook clip energy (shock, fail, splash, etc.).
- Each narration line <= 25 words. Conversational, spoken-style.
- broll_keywords are 1-2 word generic visual terms (objects, places, actions).
"""

# Tag delimiters used by reasoning models. Constructed via concatenation so
# the literal tag tokens do not appear contiguously in this source file.
_THINK_OPEN = "<" + "think" + ">"
_THINK_CLOSE = "<" + "/" + "think" + ">"


def _call_llm(topic: str, hook_name: str, hook_desc: str,
              settings: Settings) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
    resp = client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_TEMPLATE.format(
                topic=topic, hook_name=hook_name, hook_desc=hook_desc)},
        ],
        response_format={"type": "json_object"},
        max_tokens=1500,
        temperature=0.8,
    )
    return resp.choices[0].message.content or "{}"


def _parse_payload(payload: str) -> dict[str, Any]:
    """Parse the LLM response as JSON.

    Defensive against three common deviations from a clean JSON response:
    1. Markdown code fences (many "OpenAI-compatible" proxies ignore
       `response_format={"type": "json_object"}`).
    2. Reasoning-model think blocks (used by DeepSeek R1, Qwen QwQ,
       MiniMax-M3, etc. - the actual answer is below the closing tag).
    3. Leading/trailing whitespace.
    """
    text = payload.strip()
    # Strip reasoning blocks. Case-insensitive so <THINK> / <Think> also match.
    lower = text.lower()
    open_tag = _THINK_OPEN.lower()
    close_tag = _THINK_CLOSE.lower()
    # Strip matched <think>...</think> pairs.
    while open_tag in lower and close_tag in lower:
        start = lower.find(open_tag)
        end = lower.find(close_tag, start)
        if end == -1:
            break
        text = text[:start] + text[end + len(close_tag):]
        text = text.lstrip()
        lower = text.lower()
    # Strip *unclosed* <think> blocks (model ran out of tokens mid-reasoning).
    # Everything from the opening tag onward is reasoning with no JSON after it.
    if open_tag in lower and close_tag not in lower:
        start = lower.find(open_tag)
        # Check if there is any JSON-like content before the unclosed tag.
        before = text[:start].strip()
        if before:
            text = before
        else:
            # No content before the tag; discard the whole block.
            text = "{}"
        lower = text.lower()
    # Strip markdown code fences.
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1:]
        else:
            text = text.lstrip("`")
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    return json.loads(text)


def _truncate(s: str, n: int = 300) -> str:
    return s if len(s) <= n else s[:n] + f"... <{len(s) - n} more chars>"


def _fallback_script(topic: str, hook_name: str) -> Script:
    """Used when no OpenAI key is set. Keeps pipeline functional."""
    rng = random.Random(topic)
    body_templates = [
        "most people never realize this, but {topic} works like this.",
        "here is the part nobody tells you about {topic}.",
        "and once you see it, you cannot unsee it.",
        "the trick is to focus on the small details first.",
    ]
    beats = [
        Beat(role="hook_intro",
             narration=f"wait. watch this. {topic} just clicked.",
             broll_keywords=["shock", "reaction", "face"],
             target_seconds=3.0),
    ]
    for i in range(3):
        beats.append(Beat(
            role="body",
            narration=body_templates[i % len(body_templates)].format(topic=topic),
            broll_keywords=rng.sample(["closeup", "wide shot", "hands", "screen", "city", "nature"], 2),
            target_seconds=5.0,
        ))
    beats.append(Beat(role="cta",
                       narration="follow for more like this.",
                       broll_keywords=["subscribe", "like"],
                       target_seconds=3.0))
    return Script(topic=topic, hook_name=hook_name, beats=beats)


def generate(topic: str, hook_name: str, hook_desc: str,
             settings: Settings, *, retries: int = 2) -> Script:
    """Generate a Script. Falls back to template if no API key or parse fails."""
    if not settings.openai_api_key:
        return _fallback_script(topic, hook_name)

    last_err: Exception | None = None
    last_raw: str = ""
    for _ in range(retries + 1):
        try:
            raw = _call_llm(topic, hook_name, hook_desc, settings)
            data = _parse_payload(raw)
            beats = [Beat(**b) for b in data["beats"]]
            return Script(topic=topic, hook_name=hook_name, beats=beats)
        except (ValidationError, KeyError, json.JSONDecodeError) as exc:
            last_err = exc
            last_raw = locals().get("raw", last_raw)
    raise RuntimeError(
        f"Script generation failed after retries: {last_err}\n"
        f"Endpoint: {settings.openai_base_url}  Model: {settings.openai_model}\n"
        f"Raw response (first 300 chars): {_truncate(last_raw)}"
    )
