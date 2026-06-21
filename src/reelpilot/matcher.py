"""Topic <-> hook matching.

Two-stage scoring:
  1. Cheap keyword overlap (bag-of-words) to pick top candidates.
  2. Optional LLM rerank using the configured OpenAI-compatible endpoint
     (a single tiny chat completion) to pick the best hook.

Falls back to pure keyword ranking if no API key is configured.
"""

from __future__ import annotations

import re
from typing import Iterable

from .hooks import CATALOG, Hook

_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "so", "to", "of",
    "in", "on", "at", "for", "with", "by", "from", "is", "are", "was",
    "were", "be", "been", "being", "you", "your", "i", "me", "my", "we",
    "us", "our", "they", "them", "it", "its", "this", "that", "as",
}


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


def keyword_score(topic: str, hook: Hook) -> float:
    topic_tokens = _tokens(topic)
    hook_tokens = _tokens(hook.name + " " + hook.description + " " + " ".join(hook.tags))
    if not topic_tokens:
        return 0.0
    overlap = topic_tokens & hook_tokens
    partial = sum(1 for t in topic_tokens for tag in hook.tags if t in tag or tag in t)
    return len(overlap) + 0.5 * partial


def rank(topic: str, hooks: Iterable[Hook] | None = None) -> list[tuple[Hook, float]]:
    hooks = list(hooks) if hooks is not None else CATALOG
    scored = [(h, keyword_score(topic, h)) for h in hooks]
    scored.sort(key=lambda x: (-x[1], x[0].name))
    return scored


def best(topic: str, hooks: Iterable[Hook] | None = None) -> Hook:
    return rank(topic, hooks)[0][0]


def rerank_with_llm(topic: str, candidates: list[Hook], api_key: str | None,
                    base_url: str | None, model: str | None) -> list[Hook]:
    """Ask a small LLM to pick the best hook for the topic. Returns re-ordered list."""
    if not api_key or not candidates:
        return candidates

    try:
        from openai import OpenAI
    except ImportError:
        return candidates

    client = OpenAI(api_key=api_key, base_url=base_url)
    options = "\n".join(f"- {h.name}: {h.description}" for h in candidates)
    prompt = (
        "Pick the single best Malloy transitional hook for a short video on this topic.\n"
        "Reply with ONLY the hook name exactly as listed.\n\n"
        f"Topic: {topic}\n\nHooks:\n{options}"
    )
    try:
        resp = client.chat.completions.create(
            model=model or "gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=20000,
            temperature=0.0,
        )
        text = (resp.choices[0].message.content or "").strip()
    except Exception:
        return candidates

    for i, h in enumerate(candidates):
        if h.name.lower() in text.lower():
            chosen = candidates.pop(i)
            return [chosen] + candidates
    return candidates