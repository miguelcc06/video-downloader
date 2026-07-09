"""
Video Downloader — FastAPI backend
Uses yt-dlp Python API (never raw shell strings).
"""

import asyncio
import uuid
import shutil
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl

import yt_dlp

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent.parent
DOWNLOADS_DIR = BASE_DIR / "downloads"
STATIC_DIR = BASE_DIR / "static"
DOWNLOADS_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="Video Downloader", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/downloads", StaticFiles(directory=str(DOWNLOADS_DIR)), name="downloads")

# ---------------------------------------------------------------------------
# In-memory job store  (replace with Redis/DB for production)
# ---------------------------------------------------------------------------
jobs: dict[str, dict] = {}

# ---------------------------------------------------------------------------
# Quality presets
# ---------------------------------------------------------------------------
QUALITY_PRESETS = {
    "best":      "bestvideo+bestaudio/best",
    "2160p":     "bestvideo[height<=2160]+bestaudio/best[height<=2160]",
    "1080p":     "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
    "720p":      "bestvideo[height<=720]+bestaudio/best[height<=720]",
    "480p":      "bestvideo[height<=480]+bestaudio/best[height<=480]",
    "360p":      "bestvideo[height<=360]+bestaudio/best[height<=360]",
    "audio_only": "bestaudio/best",
}

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class InfoRequest(BaseModel):
    url: str

class DownloadRequest(BaseModel):
    url: str
    quality: str = "1080p"

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = STATIC_DIR / "index.html"
    return HTMLResponse(content=html_path.read_text())


@app.post("/api/info")
async def get_info(req: InfoRequest):
    """Return video metadata + available formats."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(req.url, download=False)
    except yt_dlp.utils.DownloadError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Collect unique height values for quality selector
    heights = sorted(
        {f["height"] for f in info.get("formats", []) if f.get("height")},
        reverse=True,
    )

    available = ["best", "audio_only"] + [f"{h}p" for h in heights if f"{h}p" in QUALITY_PRESETS]

    return {
        "title": info.get("title"),
        "thumbnail": info.get("thumbnail"),
        "duration": info.get("duration"),
        "uploader": info.get("uploader"),
        "view_count": info.get("view_count"),
        "available_qualities": available or list(QUALITY_PRESETS.keys()),
    }


@app.post("/api/download")
async def start_download(req: DownloadRequest, background_tasks: BackgroundTasks):
    """Kick off a background download job."""
    if req.quality not in QUALITY_PRESETS:
        raise HTTPException(status_code=400, detail=f"Unknown quality '{req.quality}'. Choose from: {list(QUALITY_PRESETS)}")

    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "pending", "progress": 0, "filename": None, "error": None}

    background_tasks.add_task(_download_worker, job_id, req.url, req.quality)
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
async def job_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs[job_id]


@app.get("/api/jobs/{job_id}/file")
async def download_file(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = jobs[job_id]
    if job["status"] != "done":
        raise HTTPException(status_code=409, detail="Download not finished yet")
    file_path = DOWNLOADS_DIR / job["filename"]
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")
    return FileResponse(
        path=str(file_path),
        media_type="application/octet-stream",
        filename=job["filename"],
    )


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

def _progress_hook(d: dict, job_id: str):
    if d["status"] == "downloading":
        pct = d.get("_percent_str", "0%").strip().replace("%", "")
        try:
            jobs[job_id]["progress"] = float(pct)
        except ValueError:
            pass
        jobs[job_id]["status"] = "downloading"
    elif d["status"] == "finished":
        jobs[job_id]["status"] = "processing"
        jobs[job_id]["progress"] = 100


def _download_worker(job_id: str, url: str, quality: str):
    fmt = QUALITY_PRESETS[quality]
    ext = "mp3" if quality == "audio_only" else "mp4"
    out_template = str(DOWNLOADS_DIR / f"{job_id}.%(ext)s")

    ydl_opts: dict = {
        "format": fmt,
        "outtmpl": out_template,
        "merge_output_format": ext,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [lambda d: _progress_hook(d, job_id)],
        "max_filesize": 2 * 1024 ** 3,  # 2 GB hard limit
    }

    if quality == "audio_only":
        ydl_opts["postprocessors"] = [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
        ]

    try:
        jobs[job_id]["status"] = "downloading"
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        # Find the output file
        candidates = list(DOWNLOADS_DIR.glob(f"{job_id}.*"))
        if not candidates:
            raise FileNotFoundError("Output file not found after download")

        jobs[job_id]["filename"] = candidates[0].name
        jobs[job_id]["status"] = "done"
        jobs[job_id]["progress"] = 100

    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(e)
