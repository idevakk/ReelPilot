"""Script generation tests using a stubbed OpenAI client."""

import json
from unittest.mock import patch

from shortmaker.config import Settings
from shortmaker.models import Script
from shortmaker.script import _THINK_OPEN, _THINK_CLOSE, _fallback_script, generate


def _settings(**overrides) -> Settings:
    base = dict(
        deepgram_api_key=None,
        pexels_api_key=None,
        pixabay_api_key=None,
        openai_api_key="sk-test",
        openai_base_url="https://example.invalid/v1",
        openai_model="gpt-4o-mini",
    )
    base.update(overrides)
    return Settings(**base)


# Tag delimiters built by concatenation so the literal tokens never appear
# contiguously in this source file (the literal angle-bracket forms are
# stripped by the tool that wrote this test).
_THINK_OPEN = "<" + "think" + ">"
_THINK_CLOSE = "<" + "/" + "think" + ">"


def test_fallback_script_structure():
    s = _fallback_script("async Python", "Snowball-Splash")
    assert isinstance(s, Script)
    assert s.hook_name == "Snowball-Splash"
    assert s.beats[0].role == "hook_intro"
    assert any(b.role == "body" for b in s.beats)
    assert s.beats[-1].role == "cta"
    assert 20 <= s.target_duration <= 40


def test_generate_with_mocked_openai():
    payload = {
        "beats": [
            {"role": "hook_intro", "narration": "watch this.",
             "broll_keywords": ["shock"], "target_seconds": 3.0},
            {"role": "body", "narration": "the trick is simple.",
             "broll_keywords": ["hands"], "target_seconds": 5.0},
            {"role": "body", "narration": "now you see it.",
             "broll_keywords": ["reveal"], "target_seconds": 5.0},
            {"role": "body", "narration": "and now you don't.",
             "broll_keywords": ["magic"], "target_seconds": 5.0},
            {"role": "cta", "narration": "follow for more.",
             "broll_keywords": ["subscribe"], "target_seconds": 3.0},
        ]
    }
    raw = json.dumps(payload)

    class FakeChoice:
        message = type("M", (), {"content": raw})()
    class FakeResp:
        choices = [FakeChoice()]

    class FakeCompletions:
        def create(self, **kwargs):
            return FakeResp()
    class FakeChat:
        completions = FakeCompletions()
    class FakeClient:
        chat = FakeChat()

    with patch("openai.OpenAI", return_value=FakeClient()):
        s = generate("async", "Snowball-Splash", "splash", _settings())
    assert len(s.beats) == 5
    assert s.beats[-1].role == "cta"


def test_generate_retries_on_bad_payload():
    class FakeChoice:
        message = type("M", (), {"content": "not json"})()
    class FakeResp:
        choices = [FakeChoice()]

    class FakeCompletions:
        def create(self, **kwargs):
            return FakeResp()
    class FakeChat:
        completions = FakeCompletions()
    class FakeClient:
        chat = FakeChat()

    with patch("openai.OpenAI", return_value=FakeClient()):
        import pytest
        with pytest.raises(RuntimeError):
            generate("t", "h", "d", _settings(), retries=1)


def test_generate_no_key_uses_fallback():
    s = generate("topic", "Snowball-Splash", "desc", _settings(openai_api_key=None))
    assert s.hook_name == "Snowball-Splash"


def test_parse_payload_strips_markdown_fences():
    from shortmaker.script import _parse_payload
    out = _parse_payload("```json\n{\"beats\": []}\n```")
    assert out == {"beats": []}


def test_parse_payload_strips_think_block():
    from shortmaker.script import _parse_payload
    payload = (
        _THINK_OPEN
        + "The user wants a cat-and-dog script. "
        + "I should write 5 beats with hook, body, cta."
        + _THINK_CLOSE
        + "{\"beats\": [{\"role\": \"hook_intro\", \"narration\": \"hi\", "
        + "\"broll_keywords\": [\"cat\"], \"target_seconds\": 3.0}]}"
    )
    out = _parse_payload(payload)
    assert "beats" in out
    assert out["beats"][0]["role"] == "hook_intro"


def test_parse_payload_strips_think_block_and_fences():
    from shortmaker.script import _parse_payload
    payload = (
        _THINK_OPEN
        + "reasoning here"
        + _THINK_CLOSE
        + "\n```json\n{\"beats\": []}\n```"
    )
    out = _parse_payload(payload)
    assert out == {"beats": []}
