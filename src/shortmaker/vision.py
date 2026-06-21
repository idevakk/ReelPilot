"""Google Gemini vision integration for deeply analyzing hook videos."""

import base64
import json
import os
import subprocess
import tempfile
from pathlib import Path
import requests

def extract_frames(video_path: Path, count: int = 3) -> list[str]:
    """Extracts base64 JPEG frames evenly spaced across the video."""
    frames = []
    
    # get duration
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)
    ])
    duration = float(out.decode().strip() or "0")
    if duration <= 0:
        return []
        
    with tempfile.TemporaryDirectory(prefix="shortmaker_vision_") as tmp:
        tmp_dir = Path(tmp)
        # extract frames at evenly spaced intervals (e.g., 25%, 50%, 75%)
        for i in range(count):
            fraction = (i + 1) / (count + 1)
            ts = duration * fraction
            out_file = tmp_dir / f"frame_{i}.jpg"
            subprocess.run([
                "ffmpeg", "-y", "-ss", str(ts), "-i", str(video_path),
                "-frames:v", "1", "-q:v", "2", "-vf", "scale=-1:480",
                str(out_file)
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            
            if out_file.exists():
                b64 = base64.b64encode(out_file.read_bytes()).decode("utf-8")
                frames.append(b64)
                
    return frames

def analyze_hook(video_path: Path, api_key: str) -> str | None:
    """Uses Gemini to analyze the emotional vibe and action of the hook."""
    frames_b64 = extract_frames(video_path, count=3)
    if not frames_b64:
        return None
        
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key={api_key}"
    
    parts = []
    for b64 in frames_b64:
        parts.append({
            "inline_data": {
                "mime_type": "image/jpeg",
                "data": b64
            }
        })
        
    prompt = (
        "You are a viral TikTok hook analyzer. These 3 frames are taken chronologically "
        "from a short, looping viral video hook.\n"
        "1. Describe exactly what physical action is happening.\n"
        "2. What is the emotional vibe or surprise element?\n"
        "3. Provide exactly ONE short paragraph. Be highly descriptive and punchy. No intros/outros."
    )
    parts.append({"text": prompt})
    
    payload = {
        "contents": [{
            "parts": parts
        }],
        "generationConfig": {
            "temperature": 0.5,
            "maxOutputTokens": 200
        }
    }
    
    try:
        r = requests.post(url, json=payload, timeout=30)
        r.raise_for_status()
        data = r.json()
        if "candidates" in data and len(data["candidates"]) > 0:
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        print(f"WARN: Gemini Vision analysis failed: {e}")
        
    return None
