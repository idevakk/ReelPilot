# shortmaker

Automated 9:16 short-form video generator. Pick a topic and a Malloy transitional hook, get a TikTok-ready MP4 with animated captions, B-roll, voiceover, and ducked background music.

## Stack

| Stage | Provider |
|---|---|
| Script writer | OpenAI-compatible chat-completions endpoint (configurable) |
| Voiceover | Deepgram Aura TTS |
| B-roll | Pexels Videos API (portrait 9:16) |
| Music | Pixabay Music API (with bundled tone fallback) |
| Word timings | faster-whisper (`small` int8, CPU) |
| Captions | ASS, TikTok pop-on style |
| Assembly | FFmpeg (subprocess) |

## Install

```powershell
scoop install ffmpeg   # or choco install ffmpeg
uv venv
uv pip install -e ".[dev]"
copy .env.example .env   # fill in API keys
```

## Run

```powershell
python -m shortmaker "POV: you finally understood async Python" --hook snowball-splash
python -m shortmaker "the trick to focus" --hook auto
```

Optional flags: `--voice aura-orion-en`, `--out path/to/out.mp4`, `--force`.

## Environment variables

- `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL` — script + rerank endpoint
- `OPENAI_REASONING_EFFORT` — configures the reasoning budget for supported OpenAI models (e.g., `low`, `medium`, `high`)
- `GEMINI_API_KEY`, `GEMINI_BASE_URL` — Gemini API endpoint for vision analysis and native script writing
- `USE_GEMINI_SCRIPT` — Set to `true` to use Gemini directly for script generation instead of the default OpenAI endpoint
- `GEMINI_VISION_MODEL`, `GEMINI_SCRIPT_MODEL` — Customizable Gemini models
- `DEEPGRAM_API_KEY` — Aura TTS
- `PEXELS_API_KEY` — B-roll
- `PIXABAY_API_KEY` — background music (optional; otherwise a synthesized tone is used)
- `OUTPUT_DIR` — default `out/`

## Layout

```
src/shortmaker/
  cli.py         typer entry point
  config.py      env + paths
  hooks.py       Malloy catalog + cache
  matcher.py     keyword score + LLM rerank
  script.py      OpenAI-compatible script writer (+ template fallback)
  tts.py         Deepgram Aura
  stt.py         faster-whisper word timings
  broll.py       Pexels search/download
  music.py       Pixabay music (+ offline fallback)
  captions.py    ASS builder
  assembly.py    FFmpeg pipeline -> final MP4
scripts/fetch_hooks.py   downloads every Malloy hook once
tests/                   smoke tests
```

## Notes

- 4 GB VRAM: faster-whisper runs on CPU by default; Ollama is not used (script generation goes to your OpenAI-compatible endpoint).
- Malloy hooks are free to use commercially per their page; `assets/hooks/LICENSE-malloy.txt` is created on first download.
- Attribution sidecar (`<slug>.txt`) is written next to every output MP4 with Pexels/Pixabay credits.