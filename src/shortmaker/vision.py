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

from openai import OpenAI

def analyze_hook(video_path: Path, api_key: str, model_name: str = "gemini-flash-latest") -> str | None:
    """Uses Gemini to analyze the emotional vibe and action of the hook."""
    frame_count = 10
    frames_b64 = extract_frames(video_path, count=frame_count)
    if not frames_b64:
        return None
        
    prompt = (
        f"You are a master storyteller and video analyst. These {frame_count} frames are taken "
        "chronologically from a viral video clip.\n"
        "I need a hyper-detailed, vivid, and emotionally rich description of exactly what happens in this clip.\n"
        "Include the exact physical actions, facial expressions, the setting, and the core surprise or 'shock value' "
        "that makes it viral.\n"
        "Do NOT write a single sentence. Write a full, highly descriptive paragraph (3-5 sentences) packed with context "
        "so that a writer who cannot see the video can perfectly visualize it and write an engaging story around it.\n"
        "Provide ONLY the description with no intro, outro, or meta-commentary."
    )
    
    content_parts = [{"type": "text", "text": prompt}]
    for b64 in frames_b64:
        content_parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
        })
        
    client = OpenAI(
        api_key=api_key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
    )
    
    try:
        resp = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": content_parts}],
            temperature=0.6,
            max_tokens=400
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"WARN: Gemini Vision analysis failed: {e}")
        
    return None
