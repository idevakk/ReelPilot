"""Script generation via an OpenAI-compatible chat-completions endpoint.

v2: re-written around viral video psychology — curiosity gaps, open loops,
pattern interrupts, and result-first hooks.  Also includes a ``generate_topic``
helper that invents a high-virality topic from a random hook.

Falls back to a small templated generator if no API key is set, so the
pipeline still works offline (assumes the user has cached B-roll + music).
"""

from __future__ import annotations

import json
import random
from typing import Any

from pydantic import ValidationError

from .config import Settings
from .models import Beat, Hook, Script

# ─── system prompt ────────────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are a master storyteller and viral video creator. "
    "You write incredibly engaging, natural-sounding, and fascinating short-form video scripts.\n\n"
    "Your style is conversational, like someone telling a mind-blowing fact or story to a friend. "
    "You never sound like an AI, an infomercial, or a cheesy marketer.\n"
    "You keep people watching by making the content genuinely fascinating and flowing naturally from one point to the next.\n"
    "Every sentence must feel like it naturally belongs and drives the story forward."
)

# ─── user template ────────────────────────────────────────────────────────

USER_TEMPLATE = """\
Write a fascinating, natural-sounding short video script.

Topic: {topic}
Hook clip: {hook_name} ({hook_desc})

IMPORTANT: Do NOT think, reason, or explain. Do NOT use <thought> or <think> blocks. Output ONLY the raw JSON object immediately.

Return strict JSON with this shape:
{{
  "beats": [
    {{
      "role": "hook_reaction",
      "narration": "<=15 words. The visual hook has JUST played in silence. Start the narration here by instantly reacting to or acknowledging the hook's vibe, then connect it to the topic.",
      "broll_keywords": ["keyword1", "keyword2"],
      "target_seconds": 3.0,
      "energy": "high",
      "transition_hint": "flash",
      "caption_emphasis": ["power_word"],
      "speed": "normal"
    }},
    {{
      "role": "body",
      "narration": "Tell the story naturally. Give genuinely interesting information.",
      "broll_keywords": ["keyword1", "keyword2"],
      "target_seconds": 5.0,
      "energy": "medium",
      "transition_hint": "auto",
      "caption_emphasis": ["key_word"],
      "speed": "normal"
    }},
    {{
      "role": "body",
      "narration": "...",
      "broll_keywords": ["..."],
      "target_seconds": 5.0,
      "energy": "medium",
      "transition_hint": "auto",
      "caption_emphasis": [],
      "speed": "normal"
    }},
    {{
      "role": "cta",
      "narration": "Wrap up with a thought-provoking final thought. Do NOT ask cheesy questions or say 'follow for more'.",
      "broll_keywords": ["keyword1", "keyword2"],
      "target_seconds": 3.0,
      "energy": "medium",
      "transition_hint": "fade",
      "caption_emphasis": [],
      "speed": "normal"
    }}
  ]
}}

STORYTELLING RULES (follow ALL):
1. HOOK SEPARATION: The hook video plays FIRST, untouched. Your script begins IMMEDIATELY AFTER the hook finishes. Find a creative angle to match the hook's visual perspective in your first sentence.
2. NARRATION: Keep sentences flowing naturally. Sound like a real person talking to a friend. No unnatural marketing speak or cliché "curiosity gaps".
3. STORY ARC: Build interest naturally. Give genuinely fascinating facts or tell a compelling story.
4. B-ROLL KEYWORDS: This is critical! We download videos from Pexels using these keywords. DO NOT USE abstract terms (like "mind_blown", "concept", "truth"). Use LITERAL, highly-searchable visual nouns and actions (e.g., "coffee cup", "people walking", "storm clouds", "scientist lab"). We prefer videos, so use highly visual terms.
5. FLOW: Make the transitions between beats smooth and effortless. Don't sound rigid.
6. energy: "high" for shocking/funny/exciting, "medium" for storytelling/reveals, "low" for emotional pauses.
7. Total duration 25-35 seconds. Body 4-6s each, CTA 2-3s.
8. broll_keywords: 2-3 specific LITERAL VISUAL terms for each beat.
"""

# ─── topic generation prompt ─────────────────────────────────────────────

TOPIC_PROMPT = """\
Generate ONE viral short-form video topic.

Hook clip being used: {hook_name} — {hook_desc}
Hook energy keywords: {tags}
Example topic styles that work with this hook:
{seeds}

The topic MUST:
1. Trigger instant curiosity (viewer NEEDS to know)
2. Be emotionally charged (shock, awe, humor, or fear)
3. Appeal to a wide audience (not niche)
4. Match the hook's energy: {hook_desc}

Return ONLY the topic text. No quotes, no explanation. Do NOT use <thought> or <think> blocks. 15 words max.
Examples of good viral topics:
- "This is why cats are secretly plotting against you"
- "The 3-second trick that makes anyone instantly like you"
- "Scientists just discovered something terrifying about sleep"
"""

# ─── think-tag stripping ─────────────────────────────────────────────────

_THINK_OPEN = "<" + "think" + ">"
_THINK_CLOSE = "<" + "/" + "think" + ">"


# ─── LLM calls ───────────────────────────────────────────────────────────

def _call_llm(
    topic: str,
    hook_name: str,
    hook_desc: str,
    settings: Settings,
) -> str:
    from openai import OpenAI

    api_key = settings.openai_api_key
    base_url = settings.openai_base_url
    model = settings.openai_model

    if settings.use_gemini_script and settings.gemini_api_key:
        api_key = settings.gemini_api_key
        base_url = settings.gemini_base_url
        model = settings.gemini_script_model

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": USER_TEMPLATE.format(
                    topic=topic, hook_name=hook_name, hook_desc=hook_desc,
                ),
            },
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": 20000,
        "temperature": 0.85,
    }
    if settings.openai_reasoning_effort and not settings.use_gemini_script:
        # Some providers want it native, some in extra_body
        kwargs["extra_body"] = {"reasoning_effort": settings.openai_reasoning_effort}
        # We also pass it natively in case the client supports it
        kwargs["reasoning_effort"] = settings.openai_reasoning_effort

    client = OpenAI(api_key=api_key, base_url=base_url)
    resp = client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content or "{}"


def generate_topic(hook: Hook, settings: Settings) -> str:
    """Use the LLM to invent a viral topic that matches *hook*'s energy."""
    
    api_key = settings.openai_api_key
    base_url = settings.openai_base_url
    model = settings.openai_model

    if settings.use_gemini_script and settings.gemini_api_key:
        api_key = settings.gemini_api_key
        base_url = settings.gemini_base_url
        model = settings.gemini_script_model

    if not api_key:
        # Offline fallback: pick from the hook's own seeds.
        if hook.topic_seeds:
            return random.choice(hook.topic_seeds)
        return f"incredible things about {random.choice(hook.tags)}"

    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url)
    seeds_text = "\n".join(f"- {s}" for s in (hook.topic_seeds or hook.tags))
    prompt = TOPIC_PROMPT.format(
        hook_name=hook.name,
        hook_desc=hook.description,
        tags=", ".join(hook.tags),
        seeds=seeds_text,
    )
    try:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 20000,
            "temperature": 0.95,
        }
        if settings.openai_reasoning_effort and not settings.use_gemini_script:
            kwargs["extra_body"] = {"reasoning_effort": settings.openai_reasoning_effort}
            kwargs["reasoning_effort"] = settings.openai_reasoning_effort

        resp = client.chat.completions.create(**kwargs)
        text = (resp.choices[0].message.content or "").strip()
        # Strip thinking blocks from the topic response too
        text = _strip_think(text).strip().strip("\"'")
        if text:
            return text
    except Exception:
        pass
    if hook.topic_seeds:
        return random.choice(hook.topic_seeds)
    return f"incredible things about {random.choice(hook.tags)}"


# ─── parsing helpers ─────────────────────────────────────────────────────

def _strip_think(text: str) -> str:
    """Remove ``<think>…</think>`` blocks (matched and unclosed)."""
    lower = text.lower()
    open_tag = _THINK_OPEN.lower()
    close_tag = _THINK_CLOSE.lower()

    # Matched pairs
    while open_tag in lower and close_tag in lower:
        start = lower.find(open_tag)
        end = lower.find(close_tag, start)
        if end == -1:
            break
        text = text[:start] + text[end + len(close_tag):]
        text = text.lstrip()
        lower = text.lower()

    # Unclosed <think> (model ran out of tokens mid-reasoning)
    if open_tag in lower and close_tag not in lower:
        start = lower.find(open_tag)
        before = text[:start].strip()
        text = before if before else "{}"
    return text


def _parse_payload(payload: str) -> dict[str, Any]:
    """Parse LLM response as JSON, stripping think blocks and code fences."""
    text = _strip_think(payload.strip())

    import re
    # Try to find JSON inside markdown code blocks
    match = re.search(r"```(?:json)?\s*(\{.*\}|\[.*\])\s*```", text, re.DOTALL)
    if match:
        text = match.group(1)
    else:
        # Fallback: extract the outermost JSON object
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start:end+1]

    if not text.strip():
        text = "{}"

    return json.loads(text)


def _truncate(s: str, n: int = 300) -> str:
    return s if len(s) <= n else s[:n] + f"... <{len(s) - n} more chars>"


# ─── fallback template ───────────────────────────────────────────────────

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
        Beat(
            role="hook_intro",
            narration=f"wait. watch this. {topic} just clicked.",
            broll_keywords=["shock", "reaction", "face"],
            target_seconds=2.5,
            energy="high",
            transition_hint="flash",
            caption_emphasis=["watch"],
        ),
    ]
    energies = ["high", "medium", "medium"]
    for i in range(3):
        beats.append(Beat(
            role="body",
            narration=body_templates[i % len(body_templates)].format(topic=topic),
            broll_keywords=rng.sample(
                ["closeup", "wide shot", "hands", "screen", "city", "nature"], 2,
            ),
            target_seconds=5.0,
            energy=energies[i],
            transition_hint="auto",
        ))
    beats.append(Beat(
        role="cta",
        narration="would you try this? be honest.",
        broll_keywords=["question", "thinking"],
        target_seconds=3.0,
        energy="medium",
        transition_hint="fade",
        caption_emphasis=["honest"],
    ))
    return Script(topic=topic, hook_name=hook_name, beats=beats)


# ─── main entry point ────────────────────────────────────────────────────

def generate(
    topic: str,
    hook_name: str,
    hook_desc: str,
    settings: Settings,
    *,
    retries: int = 2,
) -> Script:
    """Generate a Script.  Falls back to template if no API key or parse fails."""
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
