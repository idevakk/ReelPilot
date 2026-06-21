"""Pexels + Pixabay HTTP tests with mocked responses."""

import responses

from shortmaker import broll, music


@responses.activate
def test_broll_search_returns_videos():
    responses.get(
        "https://api.pexels.com/videos/search",
        json={"videos": [
            {"id": 1, "video_files": [
                {"id": "f1", "link": "https://cdn.example/a.mp4",
                 "width": 1080, "height": 1920},
            ]},
            {"id": 2, "video_files": []},
        ]},
        status=200,
    )
    out = broll.search("snow", api_key="k")
    assert len(out) == 2


@responses.activate
def test_broll_download_writes_file(tmp_path):
    responses.get(
        "https://api.pexels.com/videos/search",
        json={"videos": [
            {"id": 1, "video_files": [
                {"id": "f1", "link": "https://cdn.example/a.mp4",
                 "width": 1080, "height": 1920},
            ]},
        ]},
        status=200,
    )
    responses.get("https://cdn.example/a.mp4", body=b"FAKEMP4DATA", status=200)
    p = broll.download("snow", api_key="k", target_seconds=3.0)
    assert p is not None
    assert p.exists()
    assert p.stat().st_size > 0


@responses.activate
def test_broll_no_api_key_returns_none():
    assert broll.download("snow", api_key=None) is None


@responses.activate
def test_music_falls_back_to_tone(tmp_path, monkeypatch):
    # Both candidate endpoints 404 -> fallback path.
    responses.get("https://pixabay.com/api/music/", status=404)
    responses.get("https://pixabay.com/api/", status=404)
    p = music.fetch("topic", api_key="k", target_seconds=2.0)
    assert p.exists()