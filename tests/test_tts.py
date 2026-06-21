"""TTS (Deepgram) tests."""

import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

from reelpilot.audio import write_silence_wav
from reelpilot.tts import DEFAULT_VOICE, _probe_duration, synthesize


def test_probe_duration_returns_float_for_non_wav(tmp_path: Path):
    fake_mp3 = tmp_path / "fake.mp3"
    fake_mp3.write_bytes(b"ID3\x04")
    duration = _probe_duration(fake_mp3)
    assert isinstance(duration, float)


def test_synthesize_falls_back_to_silence_on_empty_response(tmp_path: Path):
    out = tmp_path / "out.wav"

    fake_resp = MagicMock()
    fake_resp.content = b""
    fake_resp.raise_for_status = MagicMock()

    with patch("reelpilot.tts.requests.post", return_value=fake_resp) as p:
        dur = synthesize("hello", out, api_key="k", target_seconds=2.0)

    assert p.called
    assert out.exists()
    assert isinstance(dur, float)
    # The fallback writes a real silence WAV we can reopen.
    with wave.open(str(out), "rb") as w:
        frames = w.getnframes()
        rate = w.getframerate()
    assert frames > 0
    assert rate > 0


def test_synthesize_uses_default_rest_format_url(tmp_path: Path):
    out = tmp_path / "out.wav"

    # Build a tiny real WAV (1 second of silence) to return from the fake
    # Deepgram response, so the probe path actually reopens a valid header.
    seed = tmp_path / "seed.wav"
    write_silence_wav(1.0, seed)
    wav_bytes = seed.read_bytes()

    fake_resp = MagicMock()
    fake_resp.content = wav_bytes
    fake_resp.raise_for_status = MagicMock()

    with patch("reelpilot.tts.requests.post", return_value=fake_resp) as p:
        synthesize(
            "hello",
            out,
            api_key="k",
            voice="aura-asteria-en",
            target_seconds=1.0,
        )

    assert p.called
    called_url = p.call_args.args[0]
    assert called_url == "https://api.deepgram.com/v1/speak?model=aura-asteria-en"

    called_headers = p.call_args.kwargs.get("headers", {})
    assert "Accept" not in called_headers
    assert called_headers.get("Content-Type") == "application/json"

    assert out.exists()
    with wave.open(str(out), "rb") as w:
        assert w.getnframes() > 0
        assert w.getframerate() > 0


def test_default_voice_is_known_valid_model():
    allowlist = {
        "aura-asteria-en",
        "aura-2-asteria-en",
        "aura-orion-en",
        "aura-2-orion-en",
        "aura-2-thalia-en",
    }
    assert DEFAULT_VOICE in allowlist, (
        f"DEFAULT_VOICE={DEFAULT_VOICE!r} is not in the allowlist of known "
        f"valid Deepgram Aura/Aura-2 models. Update DEFAULT_VOICE or extend "
        f"the allowlist."
    )
