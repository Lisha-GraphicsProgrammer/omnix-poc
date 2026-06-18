from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse, Response
import json
import os
import requests
import cv2
import numpy as np
import threading
import time
import subprocess
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="OMNIX POC API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure incidents folder exists
os.makedirs("incidents", exist_ok=True)
app.mount("/screenshots", StaticFiles(directory="incidents"), name="screenshots")

# ─── Config ────────────────────────────────────────────────────────────────
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")


def _parse_source(src):
    if src is None:
        return "test_video.mp4"
    try:
        return int(src)
    except (ValueError, TypeError):
        return str(src)


VIDEO_SOURCE_DEFAULT = _parse_source(os.getenv("VIDEO_SOURCE", "test_video.mp4"))

_settings = {
    "detection": {"alert_cooldown_frames": 150, "detection_confidence": 0.5, "bytetrack_buffer": 30},
    "alerts": {"channels": "dashboard", "deduplication_enabled": True, "email_notifications_enabled": False},
    "ai_model": {"frame_sampling": "every", "model_precision": "balanced"},
    "platform": {"llm_model": "claude-haiku", "site_name": "Site A — Construction", "api_endpoint": "http://localhost:8000"},
}

# Track running pipeline subprocess
_pipeline_process = None

# ============================================================
# CORE ENDPOINTS
# ============================================================

@app.get("/")
def root():
    return {"status": "OMNIX POC API running", "llm_provider": "ollama", "model": OLLAMA_MODEL}


@app.get("/api/incidents")
def get_incidents():
    incidents_file = Path("incidents.json")
    if not incidents_file.exists():
        return []
    with open(incidents_file, "r") as f:
        incidents = json.load(f)
    for inc in incidents:
        if "screenshot_path" in inc:
            filename = inc["screenshot_path"].replace("incidents/", "")
            inc["screenshot_url"] = f"http://localhost:8000/screenshots/{filename}"
    return incidents


@app.get("/api/pipeline")
def get_pipeline():
    with open("pipeline_config.json", "r") as f:
        return json.load(f)


@app.get("/api/stats")
def get_stats():
    incidents_file = Path("incidents.json")
    if not incidents_file.exists():
        return {"total": 0, "unique_persons": 0, "zones_affected": []}
    with open(incidents_file, "r") as f:
        incidents = json.load(f)
    return {
        "total": len(incidents),
        "unique_persons": len(set(i["person_id"] for i in incidents)),
        "zones_affected": list(set(i["zone"] for i in incidents))
    }


# ============================================================
# LLM RULE GENERATION (Ollama)
# ============================================================

SYSTEM_PROMPT = """You are OMNIX's rule generator. Convert plain English safety instructions into valid pipeline_config.json for a YOLOv8 + ByteTrack computer vision pipeline.

AVAILABLE MODELS:
- "helmet" - detects construction hardhats
- "vest" - detects safety vests
- "person" - base YOLO person detection

AVAILABLE RULE TYPES:
- "person_in_zone" - alert when any person enters zone
- "missing_in_zone" - alert when person without required gear enters
- "count_exceeded" - alert when more than N people in zone

OUTPUT FORMAT (must match exactly):
{
  "pipeline_id": "auto_<short_descriptive_name>",
  "description": "<one line description>",
  "models": {
    "helmet": "runs/detect/helmet_model/weights/best.pt",
    "vest": "runs/detect/vest_model/weights/best.pt"
  },
  "zones": [
    {
      "name": "<zone_name>",
      "coords": [[100, 200], [500, 200], [500, 600], [100, 600]]
    }
  ],
  "rules": [
    {
      "type": "<rule_type>",
      "zone": "<zone_name>",
      "required": ["<gear>"],
      "primary": "person"
    }
  ],
  "alert": {
    "severity": "high",
    "message": "<alert message>"
  },
  "cooldown_seconds": 30
}

EXAMPLES:

User: Alert when person enters loading zone
Output:
{"pipeline_id": "auto_person_loading", "description": "Person detected in loading zone", "models": {}, "zones": [{"name": "loading_zone", "coords": [[100,200],[500,200],[500,600],[100,600]]}], "rules": [{"type": "person_in_zone", "zone": "loading_zone", "required": [], "primary": "person"}], "alert": {"severity": "high", "message": "Person in loading zone"}, "cooldown_seconds": 30}

User: Alert when worker without helmet enters loading zone
Output:
{"pipeline_id": "auto_helmet_loading", "description": "Worker without helmet in loading zone", "models": {"helmet": "runs/detect/helmet_model/weights/best.pt"}, "zones": [{"name": "loading_zone", "coords": [[100,200],[500,200],[500,600],[100,600]]}], "rules": [{"type": "missing_in_zone", "zone": "loading_zone", "required": ["helmet"], "primary": "person"}], "alert": {"severity": "high", "message": "Helmet required in loading zone"}, "cooldown_seconds": 30}

Only include models in "models" that are actually needed by the rule.
Output ONLY the JSON. No markdown code fences, no explanation, no preamble."""


@app.post("/api/rules/generate")
async def generate_rule(request: Request):
    response_text = ""
    try:
        body = await request.json()
        instruction = body.get("instruction", "").strip()

        if not instruction:
            raise HTTPException(status_code=400, detail="instruction is required")

        full_prompt = f"{SYSTEM_PROMPT}\n\nUser instruction: {instruction}\n\nJSON output:"

        response = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": full_prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.1, "num_predict": 1024}
            },
            timeout=120
        )

        if response.status_code != 200:
            raise HTTPException(status_code=500, detail=f"Ollama error: {response.text}")

        result = response.json()
        response_text = result.get("response", "").strip()

        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
            response_text = response_text.strip()

        config = json.loads(response_text)

        return {
            "config": config,
            "instruction": instruction,
            "model_used": OLLAMA_MODEL,
            "provider": "ollama_local"
        }

    except requests.exceptions.ConnectionError:
        raise HTTPException(status_code=503, detail="Ollama is not running. Start it with: ollama serve")
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"LLM returned invalid JSON: {str(e)}. Raw: {response_text[:500]}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def merge_configs(existing: dict, new_cfg: dict) -> dict:
    """
    Merge a new rule config into the existing pipeline_config.json.
    - zones:  append new zones (skip duplicates by name)
    - rules:  append all new rules
    - models: union of all required models
    - alert:  keep highest severity
    - pipeline_id: combined name
    """
    SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}

    # ── Zones: merge by name (no duplicates) ──────────────────────────────────
    existing_zone_names = {z["name"] for z in existing.get("zones", [])}
    merged_zones = list(existing.get("zones", []))
    for zone in new_cfg.get("zones", []):
        if zone["name"] not in existing_zone_names:
            merged_zones.append(zone)
            existing_zone_names.add(zone["name"])

    # ── Rules: always append (same zone can have multiple rules) ──────────────
    merged_rules = list(existing.get("rules", [])) + list(new_cfg.get("rules", []))

    # ── Models: union ─────────────────────────────────────────────────────────
    merged_models = {**existing.get("models", {}), **new_cfg.get("models", {})}

    # ── Alert: keep highest severity ──────────────────────────────────────────
    existing_sev = existing.get("alert", {}).get("severity", "medium")
    new_sev      = new_cfg.get("alert", {}).get("severity", "medium")
    if SEVERITY_ORDER.get(new_sev, 1) >= SEVERITY_ORDER.get(existing_sev, 1):
        merged_alert = new_cfg.get("alert", existing.get("alert", {}))
    else:
        merged_alert = existing.get("alert", {})

    # ── Cooldown: use the shorter (more sensitive) of the two ────────────────
    merged_cooldown = min(
        existing.get("cooldown_seconds", 30),
        new_cfg.get("cooldown_seconds", 30)
    )

    # ── Pipeline ID: combine both names ───────────────────────────────────────
    existing_id = existing.get("pipeline_id", "auto_rule")
    new_id      = new_cfg.get("pipeline_id", "auto_rule")
    # Strip shared "auto_" prefix for cleaner combined name
    def strip_auto(s): return s[5:] if s.startswith("auto_") else s
    merged_id = f"auto_{strip_auto(existing_id)}__{strip_auto(new_id)}"

    # ── Description: combine ─────────────────────────────────────────────────
    existing_desc = existing.get("description", "")
    new_desc      = new_cfg.get("description", "")
    merged_desc   = f"{existing_desc} + {new_desc}" if existing_desc else new_desc

    return {
        "pipeline_id":      merged_id,
        "description":      merged_desc,
        "models":           merged_models,
        "zones":            merged_zones,
        "rules":            merged_rules,
        "alert":            merged_alert,
        "cooldown_seconds": merged_cooldown,
    }


@app.post("/api/rules/apply")
async def apply_rule(request: Request):
    """Merge new rule into pipeline_config.json and auto-launch pipeline."""
    global _pipeline_process
    try:
        body = await request.json()
        new_config = body.get("config")
        force_overwrite = body.get("overwrite", False)  # optional: force replace

        if not new_config:
            raise HTTPException(status_code=400, detail="config is required")

        config_path = Path("pipeline_config.json")

        # ── Backup existing config ────────────────────────────────────────────
        if config_path.exists():
            backup_path = Path("pipeline_config.backup.json")
            with open(config_path, "r") as src, open(backup_path, "w") as dst:
                dst.write(src.read())

        # ── Merge or overwrite ────────────────────────────────────────────────
        if config_path.exists() and not force_overwrite:
            with open(config_path, "r") as f:
                existing_config = json.load(f)
            merged = merge_configs(existing_config, new_config)
            print(f"[OMNIX] Merged rule into existing config → {merged['pipeline_id']}")
            print(f"[OMNIX] Total zones: {len(merged['zones'])}, Total rules: {len(merged['rules'])}")
        else:
            merged = new_config
            print(f"[OMNIX] New pipeline config → {merged['pipeline_id']}")

        # ── Write merged config ───────────────────────────────────────────────
        with open(config_path, "w") as f:
            json.dump(merged, f, indent=2)

        # ── Kill any existing pipeline ────────────────────────────────────────
        if _pipeline_process is not None and _pipeline_process.poll() is None:
            _pipeline_process.terminate()
            try:
                _pipeline_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _pipeline_process.kill()
            print("[OMNIX] Stopped previous pipeline process")

        # ── Clear old incidents ───────────────────────────────────────────────
        incidents_file = Path("incidents.json")
        if incidents_file.exists():
            incidents_file.unlink()
        for f in Path("incidents").glob("*.jpg"):
            try:
                f.unlink()
            except:
                pass

        # ── Launch pipeline ───────────────────────────────────────────────────
        _pipeline_process = subprocess.Popen(
            [sys.executable, "run_pipeline.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        print(f"[OMNIX] Pipeline started (PID {_pipeline_process.pid})")

        return {
            "status": "applied",
            "message": f"Rule merged and pipeline started. {len(merged['rules'])} rule(s) now active.",
            "config_path": str(config_path),
            "pipeline_id": merged["pipeline_id"],
            "total_zones": len(merged["zones"]),
            "total_rules": len(merged["rules"]),
            "pipeline_pid": _pipeline_process.pid,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/rules/reset")
def reset_rules():
    """Clear pipeline_config.json so next apply starts fresh (no merge)."""
    config_path = Path("pipeline_config.json")
    if config_path.exists():
        backup_path = Path("pipeline_config.backup.json")
        config_path.rename(backup_path)
    return {"status": "reset", "message": "Pipeline config cleared. Next rule will start fresh."}


@app.get("/api/pipeline/status")
def pipeline_status():
    """Check if the pipeline subprocess is currently running."""
    global _pipeline_process
    if _pipeline_process is None:
        return {"running": False, "pid": None, "status": "not_started"}
    poll = _pipeline_process.poll()
    if poll is None:
        return {"running": True, "pid": _pipeline_process.pid, "status": "running"}
    else:
        return {"running": False, "pid": _pipeline_process.pid, "status": "finished", "exit_code": poll}


@app.post("/api/pipeline/stop")
def stop_pipeline():
    """Stop the running pipeline subprocess."""
    global _pipeline_process
    if _pipeline_process is None or _pipeline_process.poll() is not None:
        return {"status": "not_running"}
    _pipeline_process.terminate()
    try:
        _pipeline_process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _pipeline_process.kill()
    return {"status": "stopped", "pid": _pipeline_process.pid}


# ============================================================
# VIDEO STREAMING (MJPEG)
# ============================================================

class VideoStream:
    def __init__(self):
        self.cap = None
        self.lock = threading.Lock()
        self.running = False
        self.current_frame = None
        self.fps = 0
        self.width = 0
        self.height = 0
        self.source = None

    def start(self, source):
        with self.lock:
            if self.cap:
                self.cap.release()
            self.cap = cv2.VideoCapture(source)
            if not self.cap.isOpened():
                self.cap = None
                self.running = False
                return False
            self.source = str(source)
            self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 25
            self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            self.running = True
        return True

    def read(self):
        with self.lock:
            if not self.cap or not self.running:
                return None
            ret, frame = self.cap.read()
            if not ret:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, frame = self.cap.read()
            if ret:
                self.current_frame = frame
                return frame
            return None

    def stop(self):
        with self.lock:
            self.running = False
            if self.cap:
                self.cap.release()
                self.cap = None


video_stream = VideoStream()

source_ok = (
    isinstance(VIDEO_SOURCE_DEFAULT, int)
    or (isinstance(VIDEO_SOURCE_DEFAULT, str) and VIDEO_SOURCE_DEFAULT.startswith("rtsp://"))
    or Path(VIDEO_SOURCE_DEFAULT).exists()
)
if source_ok:
    started = video_stream.start(VIDEO_SOURCE_DEFAULT)
    label = f"webcam #{VIDEO_SOURCE_DEFAULT}" if isinstance(VIDEO_SOURCE_DEFAULT, int) else VIDEO_SOURCE_DEFAULT
    print(f"[OMNIX] Video stream auto-started: {label} ({'OK' if started else 'FAILED'})")
    if not started and isinstance(VIDEO_SOURCE_DEFAULT, int):
        print(f"[OMNIX] Webcam {VIDEO_SOURCE_DEFAULT} couldn't be opened. Try VIDEO_SOURCE=1 in .env.")
else:
    print(f"[OMNIX] Video source not found: {VIDEO_SOURCE_DEFAULT}. Camera 1 will be offline.")


def generate_frames():
    target_fps = 25
    frame_interval = 1.0 / target_fps

    while True:
        start = time.time()

        frame = video_stream.read()
        if frame is None:
            placeholder = np.zeros((480, 854, 3), dtype=np.uint8)
            cv2.putText(placeholder, "NO SIGNAL", (320, 240),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.5, (80, 80, 80), 2)
            frame = placeholder
        else:
            frame = cv2.resize(frame, (854, 480))

        ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if not ret:
            continue

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' +
               buffer.tobytes() + b'\r\n')

        elapsed = time.time() - start
        sleep_time = frame_interval - elapsed
        if sleep_time > 0:
            time.sleep(sleep_time)


@app.get("/api/video/stream")
def video_stream_endpoint():
    return StreamingResponse(generate_frames(), media_type="multipart/x-mixed-replace;boundary=frame")


@app.get("/api/video/snapshot")
def video_snapshot():
    frame = video_stream.read()
    if frame is None:
        placeholder = np.zeros((480, 854, 3), dtype=np.uint8)
        cv2.putText(placeholder, "NO SIGNAL", (320, 240),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.5, (80, 80, 80), 2)
        frame = placeholder
    else:
        frame = cv2.resize(frame, (854, 480))
    ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ret:
        raise HTTPException(status_code=500, detail="Failed to encode frame")
    return Response(content=buffer.tobytes(), media_type="image/jpeg")


@app.post("/api/video/source")
async def set_video_source(request: Request):
    body = await request.json()
    raw_source = body.get("source", "")
    if isinstance(raw_source, str):
        raw_source = raw_source.strip()
    if raw_source == "" or raw_source is None:
        raise HTTPException(status_code=400, detail="source is required")

    source = _parse_source(raw_source)

    if isinstance(source, str) and not source.startswith("rtsp://") and not Path(source).exists():
        raise HTTPException(status_code=404, detail=f"File not found: {source}")

    success = video_stream.start(source)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to open video source")
    return {"status": "ok", "source": str(source), "fps": video_stream.fps}


# ============================================================
# CAMERAS
# ============================================================

@app.get("/api/cameras")
def get_cameras():
    video_ok = video_stream.running and video_stream.cap is not None

    return [
        {
            "id": 1,
            "name": "Camera 1 — Loading Zone",
            "location": "Loading zone entrance",
            "status": "online" if video_ok else "offline",
            "stream_url": "http://localhost:8000/api/video/stream" if video_ok else None,
            "snapshot_url": "http://localhost:8000/api/video/snapshot" if video_ok else None,
            "fps": int(video_stream.fps) if video_ok else 0,
            "resolution": f"{video_stream.width}x{video_stream.height}" if video_ok else "N/A",
            "source": video_stream.source or "none",
        },
        {"id": 2, "name": "Camera 2 — Crane Zone",  "location": "Crane operation area", "status": "offline", "stream_url": None, "snapshot_url": None, "fps": 0, "resolution": "N/A", "source": "none"},
        {"id": 3, "name": "Camera 3 — Storage",     "location": "Material storage",      "status": "offline", "stream_url": None, "snapshot_url": None, "fps": 0, "resolution": "N/A", "source": "none"},
        {"id": 4, "name": "Camera 4 — Exit Gate",   "location": "South exit",            "status": "offline", "stream_url": None, "snapshot_url": None, "fps": 0, "resolution": "N/A", "source": "none"},
        {"id": 5, "name": "Camera 5 — Scaffold A",  "location": "Scaffold zone A",       "status": "offline", "stream_url": None, "snapshot_url": None, "fps": 0, "resolution": "N/A", "source": "none"},
        {"id": 6, "name": "Camera 6 — Scaffold B",  "location": "Scaffold zone B",       "status": "offline", "stream_url": None, "snapshot_url": None, "fps": 0, "resolution": "N/A", "source": "none"},
        {"id": 7, "name": "Camera 7 — Warehouse",   "location": "Main warehouse",        "status": "offline", "stream_url": None, "snapshot_url": None, "fps": 0, "resolution": "N/A", "source": "none"},
        {"id": 8, "name": "Camera 8 — Rooftop",     "location": "Rooftop overview",      "status": "offline", "stream_url": None, "snapshot_url": None, "fps": 0, "resolution": "N/A", "source": "none"},
    ]


# ============================================================
# SETTINGS
# ============================================================

@app.get("/api/settings")
def get_settings():
    return _settings


@app.put("/api/settings")
async def update_settings(request: Request):
    body = await request.json()
    for section in ("detection", "alerts", "ai_model", "platform"):
        if section in body:
            _settings[section].update(body[section])
    return {"status": "saved", "settings": _settings}


# ============================================================
# DANGER ZONE
# ============================================================

@app.post("/api/danger/flush-alerts")
def flush_alerts():
    incidents_file = Path("incidents.json")
    flushed = 0
    if incidents_file.exists():
        with open(incidents_file, "r") as f:
            flushed = len(json.load(f))
        incidents_file.unlink()
    for f in Path("incidents").glob("*.jpg"):
        try: f.unlink()
        except: pass
    return {"status": "flushed", "count": flushed}


@app.post("/api/danger/reset-tracks")
def reset_tracks():
    return {"status": "tracks_reset", "note": "Restart run_pipeline.py to fully reset ByteTrack state"}