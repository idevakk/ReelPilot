import asyncio
import os
import time
import subprocess
import json
import sys
from pathlib import Path
from fastapi import FastAPI, Request, BackgroundTasks, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn
import dotenv

from .config import OUTPUT_DIR, MUSIC_LIBRARY_DIR, STATIC_DIR, PROJECT_ROOT

app = FastAPI(title="ReelPilot")

# Make sure output directory exists
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# We need a template directory
TEMPLATES_DIR = Path(__file__).parent / "templates"
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

# Mount the static output directory to serve videos
app.mount("/out", StaticFiles(directory=str(OUTPUT_DIR)), name="out")

# Mount the music library to serve audio for playback
MUSIC_LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/music", StaticFiles(directory=str(MUSIC_LIBRARY_DIR)), name="music")

STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

JOBS_DIR = OUTPUT_DIR / "_jobs"
JOBS_DIR.mkdir(parents=True, exist_ok=True)

jobs = {}

@app.get("/", response_class=HTMLResponse)
async def get_index():
    index_path = TEMPLATES_DIR / "index.html"
    if not index_path.exists():
        return HTMLResponse("<h1>index.html not found!</h1>", status_code=404)
    return index_path.read_text(encoding="utf-8")

@app.get("/api/hooks")
async def list_hooks():
    hooks_dir = Path("assets/hooks")
    if not hooks_dir.exists():
        return {"hooks": []}
    
    hooks = []
    for p in hooks_dir.glob("*.mp4"):
        hooks.append(p.stem)
    
    # Also add the special "auto" hook
    return {"hooks": ["auto"] + sorted(hooks)}

@app.get("/api/videos")
async def list_videos():
    # Videos are inside subfolders of OUTPUT_DIR
    videos = []
    for folder in OUTPUT_DIR.iterdir():
        if folder.is_dir() and not folder.name.startswith("_"):
            mp4_file = folder / f"{folder.name}.mp4"
            if mp4_file.exists():
                sidecar_file = folder / f"{folder.name}.txt"
                sidecar_content = sidecar_file.read_text(encoding="utf-8", errors="replace") if sidecar_file.exists() else ""
                
                videos.append({
                    "id": folder.name,
                    "url": f"/out/{folder.name}/{mp4_file.name}",
                    "created_at": folder.stat().st_mtime,
                    "sidecar": sidecar_content
                })
    
    videos.sort(key=lambda x: x["created_at"], reverse=True)
    return {"videos": videos}

@app.get("/api/music")
async def list_music():
    if not MUSIC_LIBRARY_DIR.exists():
        return {"music": []}
    
    music_files = []
    for p in MUSIC_LIBRARY_DIR.glob("*.*"):
        if p.suffix.lower() in (".mp3", ".wav", ".m4a"):
            music_files.append({"name": p.name, "size": p.stat().st_size})
            
    music_files.sort(key=lambda x: x["name"])
    return {"music": music_files}

@app.post("/api/music")
async def upload_music(file: UploadFile = File(...)):
    MUSIC_LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    file_path = MUSIC_LIBRARY_DIR / file.filename
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)
    return {"success": True, "filename": file.filename}

@app.delete("/api/music/{filename}")
async def delete_music(filename: str):
    file_path = MUSIC_LIBRARY_DIR / filename
    if file_path.exists():
        file_path.unlink()
        return {"success": True}
    return JSONResponse({"error": "File not found"}, status_code=404)

class GenerateRequest(BaseModel):
    topic: str | None = None
    hook: str
    voice: str = "aura-2-luna-en"
    duration: int = 30
    engine: str = "intel"
    bgm: str = "auto"

def run_generation(job_id: str, req: GenerateRequest):
    jobs[job_id] = {"status": "running"}
    log_file = JOBS_DIR / f"{job_id}.log"
    
    # Run the reelpilot CLI module as a subprocess so we can capture output
    cmd = [
        sys.executable, "-m", "reelpilot"
    ]
    if req.topic and req.topic.strip():
        cmd.append(req.topic.strip())
        
    cmd.extend([
        "--hook", req.hook,
        "--voice", req.voice,
        "--duration", str(req.duration),
        "--bgm", req.bgm
    ])
    
    with open(log_file, "w", encoding="utf-8") as f:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["RENDER_ENGINE"] = req.engine
        process = subprocess.Popen(
            cmd,
            stdout=f,
            stderr=subprocess.STDOUT,
            text=True,
            env=env
        )
        process.wait()
        
    if process.returncode == 0:
        jobs[job_id]["status"] = "completed"
    else:
        jobs[job_id]["status"] = "failed"

@app.post("/api/generate")
async def generate_video(req: GenerateRequest, bg_tasks: BackgroundTasks):
    job_id = f"job_{int(time.time())}"
    
    # Initialize log file empty
    log_file = JOBS_DIR / f"{job_id}.log"
    log_file.write_text("Starting generation...\n", encoding="utf-8")
    
    bg_tasks.add_task(run_generation, job_id, req)
    return {"job_id": job_id}

@app.get("/api/jobs/{job_id}")
async def get_job_status(job_id: str):
    log_file = JOBS_DIR / f"{job_id}.log"
    logs = log_file.read_text(encoding="utf-8", errors="replace") if log_file.exists() else ""
    
    status = jobs.get(job_id, {}).get("status", "unknown")
    
    return {
        "job_id": job_id,
        "status": status,
        "logs": logs[-5000:] # Return last 5000 chars of logs
    }

class SettingsPayload(BaseModel):
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_model: str | None = None
    openai_reasoning_effort: str | None = None
    gemini_api_key: str | None = None
    gemini_base_url: str | None = None
    use_gemini_script: str | None = None
    gemini_vision_model: str | None = None
    gemini_script_model: str | None = None
    deepgram_api_key: str | None = None
    pexels_api_key: str | None = None
    pixabay_api_key: str | None = None
    output_dir: str | None = None
    video_resolution: str | None = None
    video_fps: str | None = None
    video_quality: str | None = None
    transition_style: str | None = None
    caption_style: str | None = None

@app.get("/api/settings")
async def get_settings():
    env_path = PROJECT_ROOT / ".env"
    vals = dotenv.dotenv_values(env_path) if env_path.exists() else {}
    return {
        "openai_api_key": vals.get("OPENAI_API_KEY", ""),
        "openai_base_url": vals.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        "openai_model": vals.get("OPENAI_MODEL", "gpt-4o-mini"),
        "openai_reasoning_effort": vals.get("OPENAI_REASONING_EFFORT", ""),
        "gemini_api_key": vals.get("GEMINI_API_KEY", ""),
        "gemini_base_url": vals.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/"),
        "use_gemini_script": vals.get("USE_GEMINI_SCRIPT", "true"),
        "gemini_vision_model": vals.get("GEMINI_VISION_MODEL", "gemini-flash-latest"),
        "gemini_script_model": vals.get("GEMINI_SCRIPT_MODEL", "gemini-2.5-flash"),
        "deepgram_api_key": vals.get("DEEPGRAM_API_KEY", ""),
        "pexels_api_key": vals.get("PEXELS_API_KEY", ""),
        "pixabay_api_key": vals.get("PIXABAY_API_KEY", ""),
        "output_dir": vals.get("OUTPUT_DIR", "out"),
        "video_resolution": vals.get("VIDEO_RESOLUTION", "4k"),
        "video_fps": vals.get("VIDEO_FPS", "60"),
        "video_quality": vals.get("VIDEO_QUALITY", "final"),
        "transition_style": vals.get("TRANSITION_STYLE", "aggressive"),
        "caption_style": vals.get("CAPTION_STYLE", "bold"),
    }

@app.post("/api/settings")
async def save_settings(payload: SettingsPayload):
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        env_path.touch()
        
    mappings = {
        "OPENAI_API_KEY": payload.openai_api_key,
        "OPENAI_BASE_URL": payload.openai_base_url,
        "OPENAI_MODEL": payload.openai_model,
        "OPENAI_REASONING_EFFORT": payload.openai_reasoning_effort,
        "GEMINI_API_KEY": payload.gemini_api_key,
        "GEMINI_BASE_URL": payload.gemini_base_url,
        "USE_GEMINI_SCRIPT": payload.use_gemini_script,
        "GEMINI_VISION_MODEL": payload.gemini_vision_model,
        "GEMINI_SCRIPT_MODEL": payload.gemini_script_model,
        "DEEPGRAM_API_KEY": payload.deepgram_api_key,
        "PEXELS_API_KEY": payload.pexels_api_key,
        "PIXABAY_API_KEY": payload.pixabay_api_key,
        "OUTPUT_DIR": payload.output_dir,
        "VIDEO_RESOLUTION": payload.video_resolution,
        "VIDEO_FPS": payload.video_fps,
        "VIDEO_QUALITY": payload.video_quality,
        "TRANSITION_STYLE": payload.transition_style,
        "CAPTION_STYLE": payload.caption_style,
    }
    
    for k, v in mappings.items():
        if v is not None:
            if v == "": # Handle clearing variables
                dotenv.unset_key(env_path, k)
                if k in os.environ:
                    del os.environ[k]
            else:
                dotenv.set_key(env_path, k, v)
                os.environ[k] = v
            
    return {"success": True}

def start():
    """Starts the Uvicorn server"""
    uvicorn.run("reelpilot.web:app", host="0.0.0.0", port=8000, reload=True)
