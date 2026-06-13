from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import json
import os
import requests
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
# Ensure incidents folder exists (prevents crash on fresh checkout)
os.makedirs("incidents", exist_ok=True)

app.mount("/screenshots", StaticFiles(directory="incidents"), name="screenshots")

# Ollama config (read from .env, defaults to lightweight model)
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")

# ============================================================
# EXISTING ENDPOINTS (unchanged)
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
# NEW ENDPOINTS - LLM Rule Generation (Ollama)
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
    """Convert English instruction to pipeline_config JSON via Ollama."""
    try:
        body = await request.json()
        instruction = body.get("instruction", "").strip()
        
        if not instruction:
            raise HTTPException(status_code=400, detail="instruction is required")
        
        # Build prompt for Ollama (combines system + user message)
        full_prompt = f"{SYSTEM_PROMPT}\n\nUser instruction: {instruction}\n\nJSON output:"
        
        # Call Ollama
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": full_prompt,
                "stream": False,
                "format": "json",
                "options": {
                    "temperature": 0.1,
                    "num_predict": 1024
                }
            },
            timeout=120
        )
        
        if response.status_code != 200:
            raise HTTPException(
                status_code=500,
                detail=f"Ollama error: {response.text}"
            )
        
        result = response.json()
        response_text = result.get("response", "").strip()
        
        # Strip markdown if present (defensive)
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
        raise HTTPException(
            status_code=503,
            detail="Ollama is not running. Start it with: ollama serve"
        )
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=500,
            detail=f"LLM returned invalid JSON: {str(e)}. Raw: {response_text[:500]}"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/rules/apply")
async def apply_rule(request: Request):
    """Overwrite pipeline_config.json with new rule."""
    try:
        body = await request.json()
        config = body.get("config")
        
        if not config:
            raise HTTPException(status_code=400, detail="config is required")
        
        # Backup existing config
        existing = Path("pipeline_config.json")
        if existing.exists():
            backup_path = Path("pipeline_config.backup.json")
            with open(existing, "r") as src, open(backup_path, "w") as dst:
                dst.write(src.read())
        
        # Write new config
        with open("pipeline_config.json", "w") as f:
            json.dump(config, f, indent=2)
        
        return {
            "status": "applied",
            "message": "Rule applied. Restart pipeline to take effect.",
            "config_path": "pipeline_config.json"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
# ============================================================
# NEW ENDPOINTS - Video Streaming
# ============================================================
from fastapi.responses import StreamingResponse
import cv2
import threading
import time

# ─── Shared video state ───────────────────────────────────────────────────────
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

    def start(self, source: str):
        with self.lock:
            if self.cap:
                self.cap.release()
            self.cap = cv2.VideoCapture(source)
            if not self.cap.isOpened():
                return False
            self.source = source
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
                # Loop video
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

# Auto-start with construction.mp4 if it exists
VIDEO_SOURCE = 0
if isinstance(VIDEO_SOURCE, int) or Path(VIDEO_SOURCE).exists():
    video_stream.start(VIDEO_SOURCE)


def generate_frames(cam_id: int = 1):
    """Generate MJPEG frames for streaming."""
    target_fps = 25
    frame_interval = 1.0 / target_fps

    while True:
        start = time.time()

        frame = video_stream.read()
        if frame is None:
            # Send a black placeholder frame
            placeholder = __import__('numpy').zeros((480, 640, 3), dtype=__import__('numpy').uint8)
            cv2.putText(placeholder, "NO SIGNAL", (220, 240),
                       cv2.FONT_HERSHEY_SIMPLEX, 1.5, (80, 80, 80), 2)
            frame = placeholder

        # Resize for bandwidth
        frame = cv2.resize(frame, (854, 480))

        # Encode as JPEG
        ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if not ret:
            continue

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' +
               buffer.tobytes() + b'\r\n')

        # Rate limiting
        elapsed = time.time() - start
        sleep_time = frame_interval - elapsed
        if sleep_time > 0:
            time.sleep(sleep_time)


@app.get("/api/video/stream")
def video_stream_endpoint():
    """MJPEG stream — embed directly as <img src='...'> in browser."""
    return StreamingResponse(
        generate_frames(1),
        media_type="multipart/x-mixed-replace;boundary=frame"
    )

@app.get("/api/video/snapshot")
def video_snapshot():
    """Return a single JPEG frame as a snapshot."""
    frame = video_stream.read()
    if frame is None:
        raise HTTPException(status_code=503, detail="No video source available")
    frame = cv2.resize(frame, (854, 480))
    ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ret:
        raise HTTPException(status_code=500, detail="Failed to encode frame")
    from fastapi.responses import Response
    return Response(content=buffer.tobytes(), media_type="image/jpeg")


@app.get("/api/cameras")
def get_cameras():
    """Return camera list with live status."""
    video_ok = video_stream.running and video_stream.cap is not None

    cameras = [
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
        {"id": 2, "name": "Camera 2 — Crane Zone",    "location": "Crane operation area",  "status": "offline", "stream_url": None, "snapshot_url": None, "fps": 0, "resolution": "N/A", "source": "none"},
        {"id": 3, "name": "Camera 3 — Storage",       "location": "Material storage",       "status": "offline", "stream_url": None, "snapshot_url": None, "fps": 0, "resolution": "N/A", "source": "none"},
        {"id": 4, "name": "Camera 4 — Exit Gate",     "location": "South exit",             "status": "offline", "stream_url": None, "snapshot_url": None, "fps": 0, "resolution": "N/A", "source": "none"},
        {"id": 5, "name": "Camera 5 — Scaffold A",    "location": "Scaffold zone A",        "status": "offline", "stream_url": None, "snapshot_url": None, "fps": 0, "resolution": "N/A", "source": "none"},
        {"id": 6, "name": "Camera 6 — Scaffold B",    "location": "Scaffold zone B",        "status": "offline", "stream_url": None, "snapshot_url": None, "fps": 0, "resolution": "N/A", "source": "none"},
        {"id": 7, "name": "Camera 7 — Warehouse",     "location": "Main warehouse",         "status": "offline", "stream_url": None, "snapshot_url": None, "fps": 0, "resolution": "N/A", "source": "none"},
        {"id": 8, "name": "Camera 8 — Rooftop",       "location": "Rooftop overview",       "status": "offline", "stream_url": None, "snapshot_url": None, "fps": 0, "resolution": "N/A", "source": "none"},
    ]
    return cameras


@app.post("/api/video/source")
async def set_video_source(request: Request):
    """Change video source (file path or RTSP URL)."""
    body = await request.json()
    source = body.get("source", "").strip()
    if not source:
        raise HTTPException(status_code=400, detail="source is required")
    if not Path(source).exists() and not source.startswith("rtsp://"):
        raise HTTPException(status_code=404, detail=f"File not found: {source}")
    success = video_stream.start(source)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to open video source")
    return {"status": "ok", "source": source, "fps": video_stream.fps}