from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse, Response
from sqlalchemy.orm import Session
from pydantic import BaseModel
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
from datetime import datetime, timedelta
from collections import defaultdict
import csv
import io

from db.session import get_db, SessionLocal
from db.models import User, Rule, Incident, Camera as CameraModel, Site, Zone, Setting
from auth.password import hash_password, verify_password
from auth.jwt_handler import create_token
from auth.dependencies import get_current_user
from db.seed import seed
from sqlalchemy import func

load_dotenv()

# ── B3: Read PUBLIC_BASE_URL from env ──
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")

app = FastAPI(title="OMNIX POC API")

# ── B1: CORS from env variable ──
_raw_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173")
ALLOWED_ORIGINS = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("incidents", exist_ok=True)
app.mount("/screenshots", StaticFiles(directory="incidents"), name="screenshots")

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")

ZONE_COLORS = ["#00D4FF", "#00E676", "#FFB300", "#7C3AED", "#FF4444", "#FF6B6B", "#818cf8", "#f472b6"]

# ── RTSP Phase 2: reconnect tuning ──
RECONNECT_INTERVAL_SECONDS = 5
CONSECUTIVE_FAILURE_THRESHOLD = 10


def _parse_source(src):
    if src is None:
        return "mega_cctv.mp4"
    try:
        return int(src)
    except (ValueError, TypeError):
        return str(src)


VIDEO_SOURCE_DEFAULT = _parse_source(os.getenv("VIDEO_SOURCE", "mega_cctv.mp4"))

# ============================================================
# SETTINGS — Task 3: DB-backed instead of in-memory dict
# ============================================================

DEFAULT_SETTINGS = {
    "detection": {"alert_cooldown_frames": 150, "detection_confidence": 0.5, "bytetrack_buffer": 30, "persistence_frames": 5},
    "alerts": {"channels": "dashboard", "deduplication_enabled": True, "email_notifications_enabled": False},
    "ai_model": {"frame_sampling": "every", "model_precision": "balanced"},
    "platform": {"llm_model": "claude-haiku", "site_name": "Site A — Construction", "api_endpoint": PUBLIC_BASE_URL},
}


def get_settings_for_site(db: Session, site_id: int) -> dict:
    """DB-backed settings, merged over defaults. Settings are stored one row per section (site-wide, not per-user)."""
    settings = json.loads(json.dumps(DEFAULT_SETTINGS))  # deep copy
    rows = db.query(Setting).filter(Setting.site_id == site_id, Setting.user_id.is_(None)).all()
    for row in rows:
        if row.key in settings and isinstance(row.value, dict):
            settings[row.key].update(row.value)
    return settings


def save_settings_for_site(db: Session, site_id: int, updates: dict):
    for section in ("detection", "alerts", "ai_model", "platform"):
        if section not in updates:
            continue
        existing_row = db.query(Setting).filter(
            Setting.site_id == site_id, Setting.key == section, Setting.user_id.is_(None)
        ).first()
        current = get_settings_for_site(db, site_id)[section]
        current.update(updates[section])
        if existing_row:
            existing_row.value = current
        else:
            db.add(Setting(site_id=site_id, user_id=None, key=section, value=current))
    db.commit()


_pipeline_process = None


# ============================================================
# VIDEO STREAMING — per-camera dict (RTSP Phase 1) + reconnect (Phase 2)
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
        self.is_live = False  # True for rtsp:// or webcam index; False for local files
        self._consecutive_failures = 0

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
            self.is_live = isinstance(source, int) or (isinstance(source, str) and source.startswith("rtsp://"))
            self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 25
            self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            self.running = True
            self._consecutive_failures = 0
        return True

    def read(self):
        with self.lock:
            if not self.cap or not self.running:
                return None
            ret, frame = self.cap.read()
            if not ret:
                if self.is_live:
                    # Live source (RTSP/webcam): looping to frame 0 is meaningless here.
                    # Track consecutive failures instead of retrying immediately.
                    self._consecutive_failures += 1
                    if self._consecutive_failures >= CONSECUTIVE_FAILURE_THRESHOLD:
                        print(f"[OMNIX] Stream dead after {self._consecutive_failures} consecutive failed reads: {self.source}")
                        self.running = False
                        if self.cap:
                            self.cap.release()
                            self.cap = None
                    return None
                else:
                    # Local file: loop back to start (unchanged existing behavior)
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ret, frame = self.cap.read()
            if ret:
                self.current_frame = frame
                self._consecutive_failures = 0
                return frame
            return None

    def stop(self):
        with self.lock:
            self.running = False
            if self.cap:
                self.cap.release()
                self.cap = None


# camera_id -> VideoStream. Replaces the old single global `video_stream`.
video_streams: dict[int, VideoStream] = {}
_video_streams_lock = threading.Lock()


def _camera_source_for(camera_id: int, db: Session):
    """
    Resolve the actual source to open for a camera.
    DB source wins. Camera 1 falls back to VIDEO_SOURCE_DEFAULT (.env) if the
    DB source is unset/placeholder, so existing dev setups keep working unchanged.
    """
    cam = db.query(CameraModel).filter(CameraModel.id == camera_id).first()
    if cam and cam.source and cam.source != "default":
        return _parse_source(cam.source)
    if camera_id == 1:
        return VIDEO_SOURCE_DEFAULT
    return None


def get_or_start_stream(camera_id: int, db: Session):
    """Returns a running VideoStream for camera_id, starting one if needed. None if source can't be resolved/opened."""
    with _video_streams_lock:
        vs = video_streams.get(camera_id)
        if vs is not None and vs.running:
            return vs
        source = _camera_source_for(camera_id, db)
        if source is None:
            return None
        vs = VideoStream()
        if not vs.start(source):
            return None
        video_streams[camera_id] = vs
        return vs


def restart_stream(camera_id: int, db: Session):
    """Force-stop and reopen a camera's stream (used after its source changes)."""
    with _video_streams_lock:
        old = video_streams.pop(camera_id, None)
        if old:
            old.stop()
    return get_or_start_stream(camera_id, db)


def _reconnect_monitor():
    """Background loop: checks for dead streams every RECONNECT_INTERVAL_SECONDS
    and attempts to reconnect them, updating each camera's DB status along the way."""
    while True:
        time.sleep(RECONNECT_INTERVAL_SECONDS)
        db = SessionLocal()
        try:
            with _video_streams_lock:
                dead_camera_ids = [cid for cid, vs in video_streams.items() if not vs.running]
            for cid in dead_camera_ids:
                cam = db.query(CameraModel).filter(CameraModel.id == cid).first()
                if cam:
                    cam.status = "offline"
                    db.commit()
                print(f"[OMNIX] Attempting reconnect for camera {cid}...")
                vs = get_or_start_stream(cid, db)
                if vs:
                    print(f"[OMNIX] Camera {cid} reconnected successfully")
                    if cam:
                        cam.status = "online"
                        db.commit()
                else:
                    print(f"[OMNIX] Camera {cid} reconnect failed, retrying in {RECONNECT_INTERVAL_SECONDS}s")
        except Exception as e:
            print(f"[OMNIX] Reconnect monitor error: {e}")
        finally:
            db.close()


@app.on_event("startup")
def on_startup():
    seed()
    db = SessionLocal()
    try:
        for cam in db.query(CameraModel).all():
            vs = get_or_start_stream(cam.id, db)
            cam.status = "online" if vs else "offline"
            print(f"[OMNIX] Camera {cam.id} ({cam.name}): {'started' if vs else 'offline'} — source={cam.source}")
        db.commit()
    finally:
        db.close()
    threading.Thread(target=_reconnect_monitor, daemon=True).start()
    print(f"[OMNIX] Reconnect monitor started (checks every {RECONNECT_INTERVAL_SECONDS}s)")


# ============================================================
# AUTH ENDPOINTS
# ============================================================

class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str = ""
    site_name: str = "My Site"


@app.post("/api/auth/login")
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_token(user.id)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {"id": user.id, "email": user.email, "name": user.name, "role": user.role}
    }


@app.post("/api/auth/register")
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == body.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    site = Site(name=body.site_name, location="")
    db.add(site)
    db.flush()
    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        name=body.name,
        role="admin",
        site_id=site.id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_token(user.id)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {"id": user.id, "email": user.email, "name": user.name, "role": user.role, "site_id": user.site_id}
    }


@app.get("/api/auth/me")
def me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "email": current_user.email,
        "name": current_user.name,
        "role": current_user.role,
        "site_id": current_user.site_id,
    }


# ============================================================
# USER MANAGEMENT
# ============================================================

@app.post("/api/users/invite")
async def invite_user(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can invite users")
    body = await request.json()
    email = body.get("email", "").strip()
    name = body.get("name", "").strip()
    if not email:
        raise HTTPException(status_code=400, detail="email is required")
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    viewer = User(
        email=email,
        password_hash=hash_password("changeme123"),
        name=name or email.split("@")[0],
        role="viewer",
        site_id=current_user.site_id,
    )
    db.add(viewer)
    db.commit()
    db.refresh(viewer)
    return {
        "status": "invited",
        "user": {"id": viewer.id, "email": viewer.email, "name": viewer.name, "role": viewer.role}
    }


@app.get("/api/users")
def get_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can view team members")
    users = db.query(User).filter(User.site_id == current_user.site_id).all()
    return [
        {
            "id": u.id,
            "email": u.email,
            "name": u.name,
            "role": u.role,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in users
    ]


# ============================================================
# ZONES
# ============================================================

@app.get("/api/zones")
def get_zones(
    camera_id: int = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    q = db.query(Zone).filter(Zone.site_id == current_user.site_id)
    if camera_id is not None:
        q = q.filter(Zone.camera_id == camera_id)
    zones = q.all()
    return [
        {
            "id": z.id,
            "name": z.name,
            "polygon": z.polygon,
            "color": z.color,
            "camera_id": z.camera_id,
            "created_at": z.created_at.isoformat() if z.created_at else None,
        }
        for z in zones
    ]


@app.post("/api/zones")
async def create_zone(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Viewers cannot create zones")
    body = await request.json()
    name = body.get("name", "").strip()
    polygon = body.get("polygon", [])
    camera_id = body.get("camera_id", None)
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    if len(polygon) < 3:
        raise HTTPException(status_code=400, detail="polygon must have at least 3 points")
    count = db.query(Zone).filter(Zone.site_id == current_user.site_id).count()
    color = body.get("color", ZONE_COLORS[count % len(ZONE_COLORS)])

    if camera_id is not None:
        cam = db.query(CameraModel).filter(CameraModel.id == camera_id).first()
        if cam is None:
            cam = CameraModel(
                id=camera_id,
                site_id=current_user.site_id,
                name=f"Camera {camera_id}",
                location="",
                source="default",
                status="online" if camera_id == 1 else "offline",
            )
            db.add(cam)
            db.flush()

    zone = Zone(
        site_id=current_user.site_id,
        camera_id=camera_id,
        created_by=current_user.id,
        name=name,
        polygon=polygon,
        color=color,
    )
    db.add(zone)
    db.commit()
    db.refresh(zone)
    return {
        "id": zone.id,
        "name": zone.name,
        "polygon": zone.polygon,
        "color": zone.color,
        "camera_id": zone.camera_id,
        "created_at": zone.created_at.isoformat() if zone.created_at else None,
    }


@app.put("/api/zones/{zone_id}")
async def update_zone(
    zone_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Viewers cannot edit zones")
    zone = db.query(Zone).filter(
        Zone.id == zone_id,
        Zone.site_id == current_user.site_id
    ).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")
    body = await request.json()
    if "name" in body:
        zone.name = body["name"].strip()
    if "polygon" in body:
        zone.polygon = body["polygon"]
    if "color" in body:
        zone.color = body["color"]
    db.commit()
    db.refresh(zone)
    return {
        "id": zone.id,
        "name": zone.name,
        "polygon": zone.polygon,
        "color": zone.color,
        "camera_id": zone.camera_id,
    }


@app.delete("/api/zones/{zone_id}")
def delete_zone(
    zone_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Viewers cannot delete zones")
    zone = db.query(Zone).filter(
        Zone.id == zone_id,
        Zone.site_id == current_user.site_id
    ).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")
    db.delete(zone)
    db.commit()
    return {"status": "deleted", "zone_id": zone_id}


# ============================================================
# CORE ENDPOINTS
# ============================================================

@app.get("/")
def root():
    return {"status": "OMNIX POC API running", "llm_provider": "ollama", "model": OLLAMA_MODEL}


@app.get("/api/incidents")
def get_incidents(
    limit: int = 50,
    offset: int = 0,
    rule_id: int = None,
    camera_id: int = None,
    violation: str = None,
    severity: str = None,
    review: str = None,          # "unreviewed" | "reviewed" | "false_positive" | "dismissed"
    date_from: str = None,       # ISO date e.g. 2026-07-19
    date_to: str = None,         # ISO date (inclusive)
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    try:
        base_q = db.query(Incident).filter(Incident.site_id == current_user.site_id)
        # ── Alert usability: server-side filters ──
        if rule_id is not None:
            base_q = base_q.filter(Incident.rule_id == rule_id)
        if camera_id is not None:
            base_q = base_q.filter(Incident.camera_id == camera_id)
        if violation:
            base_q = base_q.filter(Incident.violation_type == violation)
        if severity:
            base_q = base_q.filter(Incident.severity == severity.lower())
        if review == "unreviewed":
            base_q = base_q.filter(Incident.reviewed.isnot(True))
        elif review in ("reviewed", "false_positive", "dismissed"):
            base_q = base_q.filter(Incident.review_status == review)
        if date_from:
            try:
                base_q = base_q.filter(Incident.timestamp >= datetime.fromisoformat(date_from))
            except ValueError:
                pass
        if date_to:
            try:
                end = datetime.fromisoformat(date_to) + timedelta(days=1)
                base_q = base_q.filter(Incident.timestamp < end)
            except ValueError:
                pass
        total = base_q.count()
        if total >= 0:
            incidents = (
                base_q.order_by(Incident.timestamp.desc())
                .offset(offset).limit(limit).all()
            )
            # ── Alert usability: attach the plain-English rule that fired ──
            rule_ids = {inc.rule_id for inc in incidents if inc.rule_id}
            rule_map = {}
            if rule_ids:
                for r in db.query(Rule).filter(Rule.id.in_(rule_ids)).all():
                    rule_map[r.id] = r.instruction
            result = []
            for inc in incidents:
                d = {
                    "id": inc.id,
                    "rule_id": inc.rule_id,
                    "rule_instruction": rule_map.get(inc.rule_id),
                    "timestamp": inc.timestamp.isoformat() if inc.timestamp else None,
                    "violation": inc.violation_type,
                    "zone": inc.zone,
                    "severity": inc.severity,
                    "alert_message": inc.alert_message,
                    "person_id": inc.person_track_id,
                    "frame": inc.frame_number,
                    "bbox": inc.bbox,
                    "detected_objects": inc.detected_objects,
                    "missing_gear": inc.missing_gear,
                    "reviewed": inc.reviewed,
                    "review_status": inc.review_status,
                    "camera_id": inc.camera_id,
                }
                if inc.screenshot_path:
                    filename = inc.screenshot_path.replace("incidents/", "")
                    d["screenshot_url"] = f"{PUBLIC_BASE_URL}/screenshots/{filename}"
                result.append(d)
            return {"items": result, "total": total, "limit": limit, "offset": offset}
    except Exception:
        pass
    incidents_file = Path("incidents.json")
    if not incidents_file.exists():
        return {"items": [], "total": 0, "limit": limit, "offset": offset}
    with open(incidents_file, "r") as f:
        incidents = json.load(f)
    for inc in incidents:
        if "screenshot_path" in inc:
            filename = inc["screenshot_path"].replace("incidents/", "")
            inc["screenshot_url"] = f"{PUBLIC_BASE_URL}/screenshots/{filename}"
    total = len(incidents)
    return {"items": incidents[offset:offset + limit], "total": total, "limit": limit, "offset": offset}


ALLOWED_REVIEW_STATUSES = {"reviewed", "false_positive", "dismissed"}

@app.post("/api/incidents/{incident_id}/review")
async def review_incident(
    incident_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    incident = db.query(Incident).filter(
        Incident.id == incident_id,
        Incident.site_id == current_user.site_id,
    ).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    try:
        body = await request.json()
    except Exception:
        body = {}
    review_status = str(body.get("review_status") or "reviewed").strip()
    if review_status not in ALLOWED_REVIEW_STATUSES:
        raise HTTPException(status_code=400, detail=f"review_status must be one of: {', '.join(sorted(ALLOWED_REVIEW_STATUSES))}")
    incident.reviewed = True
    incident.review_status = review_status
    incident.reviewed_by = current_user.id
    incident.reviewed_at = datetime.utcnow()
    db.commit()
    return {"status": "ok", "incident_id": incident_id, "review_status": review_status}


# ── A: auth added ──
@app.get("/api/pipeline")
def get_pipeline(current_user: User = Depends(get_current_user)):
    with open("pipeline_config.json", "r") as f:
        return json.load(f)


@app.get("/api/stats")
def get_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        incidents = db.query(Incident).filter(Incident.site_id == current_user.site_id).all()
        if incidents:
            zones = list(set(i.zone for i in incidents if i.zone))
            persons = list(set(i.person_track_id for i in incidents if i.person_track_id))
            return {"total": len(incidents), "unique_persons": len(persons), "zones_affected": zones}
    except Exception:
        pass
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
# RULES
# ============================================================

@app.get("/api/rules")
def get_rules(
    all: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    q = db.query(Rule).filter(Rule.site_id == current_user.site_id)
    if not all:
        q = q.filter(Rule.status == "active")
    rules = q.order_by(Rule.created_at.desc()).all()
    counts = dict(
        db.query(Incident.rule_id, func.count(Incident.id))
        .filter(Incident.site_id == current_user.site_id)
        .group_by(Incident.rule_id).all()
    )
    return [
        {
            "id": r.id,
            "instruction": r.instruction,
            "config_json": r.config_json,
            "pipeline_id": r.pipeline_id,
            "status": r.status,
            "severity": r.severity,
            "zone_id": r.zone_id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "incident_count": counts.get(r.id, 0),
        }
        for r in rules
    ]


@app.delete("/api/rules/{rule_id}")
def delete_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Viewers cannot delete rules")
    rule = db.query(Rule).filter(
        Rule.id == rule_id,
        Rule.site_id == current_user.site_id
    ).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    rule.status = "deleted"
    db.commit()
    return {"status": "deleted", "rule_id": rule_id}


# ============================================================
# LLM RULE GENERATION
# ============================================================

SYSTEM_PROMPT = """You are OMNIX's rule generator. Convert plain English safety instructions into valid pipeline_config.json for a YOLOv8 + ByteTrack computer vision pipeline.

AVAILABLE MODELS:
- "person"   - detects people on site (base YOLOv8, COCO trained)
- "truck"    - detects trucks and heavy vehicles (base YOLOv8, COCO trained)
- "helmet"   - detects construction hardhats (custom trained)
- "fire"     - detects fire and flames (custom trained, mAP 75%)
- "smoke"    - detects smoke on site (custom trained, mAP 75%)
- "spill"    - detects liquid spills / hazardous liquids on floors (custom trained, mAP 88%)

AVAILABLE RULE TYPES:
- "person_in_zone"  - alert when any person enters zone
- "missing_in_zone" - alert when person without required gear enters
- "count_exceeded"  - alert when more than N people in zone
- "object_in_zone"  - alert when a specific OBJECT is detected inside the zone (no person needed). Use for instructions like "alert when fire/smoke/forklift/truck/ladder is detected". Set "target" to the model name, e.g. {"type": "object_in_zone", "zone": "site_area", "target": "fire", "required": []}
- "person_near_object" - alert when a person comes close to a detected object. Use "target": "<model>" and "proximity_px": <number>. For "near acid/dangerous liquid/spill/chemical", use target "spill". Example: {"type": "person_near_object", "target": "spill", "proximity_px": 120}

IMPORTANT: "alert when X is detected" (fire, smoke, forklift, truck, ladder) means object_in_zone with target X — NOT person_in_zone. Every object_in_zone rule MUST include the "target" field, e.g. "target": "fire". Never omit it.
IMPORTANT: "alert everyone near acid/spill/chemical/hazardous liquid" means person_near_object with target "spill" — NOT object_in_zone (this rule cares about people approaching the object, not just the object's presence). Never omit "target" on a person_near_object rule.
OUTPUT FORMAT (must match exactly):
{
  "pipeline_id": "auto_<short_descriptive_name>",
  "description": "<one line description>",
  "models": {
    "helmet": "runs/detect/helmet_model/weights/best.pt"
  },
  "zones": [{"name": "<zone_name>", "coords": [[100,200],[500,200],[500,600],[100,600]]}],
   "rules": [{"type": "<rule_type>", "zone": "<zone_name>", "required": ["<gear>"], "primary": "person", "target": "<object_model_if_object_in_zone>"}],
  "alert": {"severity": "high", "message": "<alert message>"},
  "cooldown_seconds": 30
}

Only include models actually needed. Output ONLY the JSON. No markdown, no explanation."""


# ── A: auth added ──
@app.post("/api/rules/generate")
async def generate_rule(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    response_text = ""
    try:
        body = await request.json()
        instruction = body.get("instruction", "").strip()
        existing_zones = body.get("existing_zones", [])
        if not instruction:
            raise HTTPException(status_code=400, detail="instruction is required")
        camera_id = body.get("camera_id")
        zone_names = []
        if camera_id is not None:
            try:
                zone_names = [z.name for z in db.query(Zone).filter(Zone.camera_id == camera_id).all()]
            except Exception:
                zone_names = []
        if not zone_names and existing_zones:
            zone_names = [z["name"] for z in existing_zones if isinstance(z, dict) and "name" in z]
        zone_context = ""
        if zone_names:
            zone_context = f"\n\nEXISTING ZONES: {', '.join(zone_names)}\nUse these zone names directly."
        full_prompt = f"{SYSTEM_PROMPT}{zone_context}\n\nUser instruction: {instruction}\n\nJSON output:"
        response = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": full_prompt, "stream": False, "format": "json", "options": {"temperature": 0.1, "num_predict": 1024}},
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
        # ── Sanitizer: object_in_zone AND person_near_object rules must carry a
        # target; if the LLM forgot, infer it from the models it selected. ──
        model_keys = [m for m in config.get("models", {}).keys() if m != "person"]
        for r in config.get("rules", []):
            if r.get("type") in ("object_in_zone", "person_near_object") and not r.get("target"):
                if r.get("required"):
                    r["target"] = r["required"][0]
                elif model_keys:
                    r["target"] = model_keys[0]
                    print(f"[OMNIX] Sanitizer: filled missing target='{model_keys[0]}' on {r.get('type')} rule")
            # person_near_object without proximity_px gets the spec's default (854x480-relative, scaled by the pipeline)
            if r.get("type") == "person_near_object" and not r.get("proximity_px"):
                r["proximity_px"] = 120
        return {"config": config, "instruction": instruction, "model_used": OLLAMA_MODEL, "provider": "ollama_local"}
    except requests.exceptions.ConnectionError:
        raise HTTPException(status_code=503, detail="Ollama is not running. Start it with: ollama serve")
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"LLM returned invalid JSON: {str(e)}. Raw: {response_text[:500]}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def enrich_zone_coords(config: dict, db: Session, site_id: int) -> dict:
    zones = config.get("zones", [])
    if not zones:
        return config
    try:
        db_zones = {z.name: z.polygon for z in db.query(Zone).filter(Zone.site_id == site_id).all()}
    except Exception as e:
        print(f"[OMNIX] Zone enrichment skipped (DB error): {e}")
        return config
    for zone in zones:
        name = zone.get("name")
        polygon = db_zones.get(name)
        if polygon and len(polygon) >= 3:
            zone["coords"] = polygon
            zone["source"] = "user_drawn"
            print(f"[OMNIX] Zone '{name}': using user-drawn polygon ({len(polygon)} points)")
    return config


def merge_configs(existing: dict, new_cfg: dict) -> dict:
    SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    existing_zone_names = {z["name"] for z in existing.get("zones", [])}
    merged_zones = list(existing.get("zones", []))
    for zone in new_cfg.get("zones", []):
        if zone["name"] not in existing_zone_names:
            merged_zones.append(zone)
            existing_zone_names.add(zone["name"])
    merged_rules = list(existing.get("rules", [])) + list(new_cfg.get("rules", []))
    merged_models = {**existing.get("models", {}), **new_cfg.get("models", {})}
    existing_sev = existing.get("alert", {}).get("severity", "medium")
    new_sev = new_cfg.get("alert", {}).get("severity", "medium")
    merged_alert = new_cfg.get("alert", existing.get("alert", {})) if SEVERITY_ORDER.get(new_sev, 1) >= SEVERITY_ORDER.get(existing_sev, 1) else existing.get("alert", {})
    merged_cooldown = min(existing.get("cooldown_seconds", 30), new_cfg.get("cooldown_seconds", 30))
    def strip_auto(s): return s[5:] if s.startswith("auto_") else s
    merged_id = f"auto_{strip_auto(existing.get('pipeline_id', 'auto_rule'))}__{strip_auto(new_cfg.get('pipeline_id', 'auto_rule'))}"
    existing_desc = existing.get("description", "")
    new_desc = new_cfg.get("description", "")
    return {
        "pipeline_id": merged_id,
        "description": f"{existing_desc} + {new_desc}" if existing_desc else new_desc,
        "models": merged_models,
        "zones": merged_zones,
        "rules": merged_rules,
        "alert": merged_alert,
        "cooldown_seconds": merged_cooldown,
    }


@app.post("/api/rules/apply")
async def apply_rule(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    global _pipeline_process
    try:
        body = await request.json()
        new_config = body.get("config")
        instruction = body.get("instruction", "")
        force_overwrite = body.get("overwrite", False)
        # ── RTSP Phase 1: which camera this rule/pipeline run applies to ──
        camera_id = int(body.get("camera_id") or 1)
        if not new_config:
            raise HTTPException(status_code=400, detail="config is required")
        if current_user.role != "admin":
            raise HTTPException(status_code=403, detail="Viewers cannot apply rules")
        try:
            # ── Rule dedupe: re-applying the same instruction replaces the old
            # row instead of stacking identical active rules forever. ──
            dupes = db.query(Rule).filter(
                Rule.site_id == current_user.site_id,
                Rule.status == "active",
                Rule.instruction == instruction,
            ).all()
            for d in dupes:
                d.status = "replaced"
            if dupes:
                print(f"[OMNIX] Dedupe: marked {len(dupes)} identical active rule(s) as replaced")
            rule = Rule(
                site_id=current_user.site_id, user_id=current_user.id,
                instruction=instruction, config_json=new_config,
                pipeline_id=new_config.get("pipeline_id"), status="active",
                severity=new_config.get("alert", {}).get("severity", "medium"),
            )
            db.add(rule)
            db.commit()
            db.refresh(rule)
            # ── stamp each new rule with its DB id so incidents attribute correctly ──
            for r in new_config.get("rules", []):
                r["rule_db_id"] = rule.id
        except Exception as e:
            print(f"[OMNIX] Warning: could not save rule to DB: {e}")
        config_path = Path("pipeline_config.json")
        if config_path.exists():
            backup_path = Path("pipeline_config.backup.json")
            with open(config_path, "r") as src, open(backup_path, "w") as dst:
                dst.write(src.read())
        if config_path.exists() and not force_overwrite:
            with open(config_path, "r") as f:
                existing_config = json.load(f)
            merged = merge_configs(existing_config, new_config)
        else:
            merged = new_config
        merged = enrich_zone_coords(merged, db, current_user.site_id)

        # ── Task 3: inject site-wide settings into the pipeline config at apply time ──
        site_settings = get_settings_for_site(db, current_user.site_id)
        merged["persistence_frames"] = site_settings["detection"].get("persistence_frames", 5)
        merged["alert_cooldown_frames"] = site_settings["detection"].get("alert_cooldown_frames", 150)
        merged["detection_confidence"] = site_settings["detection"].get("detection_confidence", 0.5)

        with open(config_path, "w") as f:
            json.dump(merged, f, indent=2)
        if _pipeline_process is not None and _pipeline_process.poll() is None:
            _pipeline_process.terminate()
            try:
                _pipeline_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _pipeline_process.kill()
        incidents_file = Path("incidents.json")
        if incidents_file.exists():
            incidents_file.unlink()
        # ── RTSP Phase 1: pass the real camera_id through to run_pipeline.py ──
        _pipeline_process = subprocess.Popen(
            [sys.executable, "run_pipeline.py", "--camera_id", str(camera_id)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
        )
        return {
            "status": "applied",
            "message": f"Rule merged and pipeline started. {len(merged['rules'])} rule(s) now active.",
            "config_path": str(config_path),
            "pipeline_id": merged["pipeline_id"],
            "total_zones": len(merged["zones"]),
            "total_rules": len(merged["rules"]),
            "pipeline_pid": _pipeline_process.pid,
            "camera_id": camera_id,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/rules/reset")
def reset_rules(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Viewers cannot reset rules")
    # ── Real reset: deactivate the DB rules too, not just the config file.
    # (Previously rules stayed "active" in the DB and re-accumulated.) ──
    deactivated = db.query(Rule).filter(
        Rule.site_id == current_user.site_id,
        Rule.status == "active",
    ).update({"status": "inactive"})
    db.commit()
    config_path = Path("pipeline_config.json")
    backup_path = Path("pipeline_config.backup.json")
    if config_path.exists():
        if backup_path.exists():
            backup_path.unlink()
        config_path.rename(backup_path)
    return {"status": "reset", "message": f"Pipeline config cleared, {deactivated} rule(s) deactivated."}


# ── A: auth added ──
@app.get("/api/pipeline/status")
def pipeline_status(current_user: User = Depends(get_current_user)):
    global _pipeline_process
    if _pipeline_process is None:
        return {"running": False, "pid": None, "status": "not_started"}
    poll = _pipeline_process.poll()
    if poll is None:
        return {"running": True, "pid": _pipeline_process.pid, "status": "running"}
    return {"running": False, "pid": _pipeline_process.pid, "status": "finished", "exit_code": poll}


# ── A: auth + admin added ──
@app.post("/api/pipeline/stop")
def stop_pipeline(current_user: User = Depends(get_current_user)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can stop the pipeline")
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
# VIDEO STREAMING — endpoints (per-camera)
# ============================================================

def generate_frames(camera_id: int):
    target_fps = 25
    frame_interval = 1.0 / target_fps
    while True:
        start = time.time()
        vs = video_streams.get(camera_id)
        frame = vs.read() if vs else None
        if frame is None:
            placeholder = np.zeros((480, 854, 3), dtype=np.uint8)
            cv2.putText(placeholder, "NO SIGNAL", (320, 240), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (80, 80, 80), 2)
            frame = placeholder
        else:
            frame = cv2.resize(frame, (854, 480))
        ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if not ret:
            continue
        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
        elapsed = time.time() - start
        sleep_time = frame_interval - elapsed
        if sleep_time > 0:
            time.sleep(sleep_time)


def generate_placeholder_frames():
    placeholder = np.zeros((480, 854, 3), dtype=np.uint8)
    cv2.putText(placeholder, "NO SIGNAL", (320, 240), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (80, 80, 80), 2)
    ret, buffer = cv2.imencode('.jpg', placeholder, [cv2.IMWRITE_JPEG_QUALITY, 75])
    payload = (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
    while True:
        yield payload
        time.sleep(0.5)


@app.get("/api/video/stream")
def video_stream_endpoint(camera_id: int = 1, db: Session = Depends(get_db)):
    vs = get_or_start_stream(camera_id, db)
    gen = generate_frames(camera_id) if vs else generate_placeholder_frames()
    return StreamingResponse(gen, media_type="multipart/x-mixed-replace;boundary=frame")


@app.get("/api/video/snapshot")
def video_snapshot(camera_id: int = 1, db: Session = Depends(get_db)):
    vs = get_or_start_stream(camera_id, db)
    frame = vs.read() if vs else None
    if frame is None:
        placeholder = np.zeros((480, 854, 3), dtype=np.uint8)
        cv2.putText(placeholder, "NO SIGNAL", (320, 240), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (80, 80, 80), 2)
        frame = placeholder
    else:
        frame = cv2.resize(frame, (854, 480))
    ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ret:
        raise HTTPException(status_code=500, detail="Failed to encode frame")
    return Response(content=buffer.tobytes(), media_type="image/jpeg")


# ── A: auth + admin added. Now per-camera; camera_id defaults to 1 for back-compat ──
@app.post("/api/video/source")
async def set_video_source(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can change video source")
    body = await request.json()
    raw_source = body.get("source", "")
    camera_id = int(body.get("camera_id") or 1)
    if isinstance(raw_source, str):
        raw_source = raw_source.strip()
    if raw_source == "" or raw_source is None:
        raise HTTPException(status_code=400, detail="source is required")
    source = _parse_source(raw_source)
    if isinstance(source, str) and not source.startswith("rtsp://") and not Path(source).exists():
        raise HTTPException(status_code=404, detail=f"File not found: {source}")
    with _video_streams_lock:
        vs = video_streams.get(camera_id) or VideoStream()
        success = vs.start(source)
        if success:
            video_streams[camera_id] = vs
    if not success:
        raise HTTPException(status_code=500, detail="Failed to open video source")
    return {"status": "ok", "source": str(source), "fps": vs.fps, "camera_id": camera_id}


# ============================================================
# CAMERAS — reads from DB, per-camera live status
# ============================================================

class CameraCreateRequest(BaseModel):
    name: str
    location: str = ""
    source: str


class CameraUpdateRequest(BaseModel):
    name: str | None = None
    location: str | None = None
    source: str | None = None


def _validate_source(source: str) -> str:
    source = (source or "").strip()
    if not source:
        raise HTTPException(status_code=400, detail="source is required")
    if source.startswith("rtsp://"):
        return source
    if source.isdigit():
        return source  # webcam index — validated on actual open attempt
    if not Path(source).exists():
        raise HTTPException(status_code=404, detail=f"File not found: {source}")
    return source


# ── A: auth added, C1: reads from DB, now per-camera live status ──
@app.get("/api/cameras")
def get_cameras(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    cameras = db.query(CameraModel).filter(
        CameraModel.site_id == current_user.site_id
    ).order_by(CameraModel.id).all()

    result = []
    for cam in cameras:
        vs = video_streams.get(cam.id)
        is_live = vs is not None and vs.running and vs.cap is not None
        result.append({
            "id": cam.id,
            "name": cam.name,
            "location": cam.location,
            "status": "online" if is_live else cam.status,
            "stream_url":   f"{PUBLIC_BASE_URL}/api/video/stream?camera_id={cam.id}"   if is_live else None,
            "snapshot_url": f"{PUBLIC_BASE_URL}/api/video/snapshot?camera_id={cam.id}" if is_live else None,
            "fps":        int(vs.fps) if is_live else 0,
            "resolution": f"{vs.width}x{vs.height}" if is_live else "N/A",
            "source": vs.source if is_live else cam.source,
        })
    return result


@app.post("/api/cameras")
def create_camera(
    body: CameraCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can add cameras")
    validated_source = _validate_source(body.source)
    cam = CameraModel(
        site_id=current_user.site_id,
        name=(body.name or "").strip() or "Unnamed Camera",
        location=(body.location or "").strip(),
        source=validated_source,
        status="offline",
    )
    db.add(cam)
    db.commit()
    db.refresh(cam)

    vs = get_or_start_stream(cam.id, db)
    cam.status = "online" if vs else "offline"
    if vs:
        cam.fps = int(vs.fps)
        cam.resolution = f"{vs.width}x{vs.height}"
    db.commit()
    db.refresh(cam)

    return {
        "id": cam.id, "name": cam.name, "location": cam.location,
        "source": cam.source, "status": cam.status,
        "fps": cam.fps, "resolution": cam.resolution,
    }


@app.put("/api/cameras/{camera_id}")
def update_camera(
    camera_id: int,
    body: CameraUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can edit cameras")
    cam = db.query(CameraModel).filter(
        CameraModel.id == camera_id,
        CameraModel.site_id == current_user.site_id
    ).first()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")

    if body.name is not None:
        cam.name = body.name.strip()
    if body.location is not None:
        cam.location = body.location.strip()

    source_changed = False
    if body.source is not None:
        cam.source = _validate_source(body.source)
        source_changed = True

    db.commit()

    if source_changed:
        vs = restart_stream(camera_id, db)
        cam.status = "online" if vs else "offline"
        if vs:
            cam.fps = int(vs.fps)
            cam.resolution = f"{vs.width}x{vs.height}"
        db.commit()
        db.refresh(cam)

    return {
        "id": cam.id, "name": cam.name, "location": cam.location,
        "source": cam.source, "status": cam.status,
        "fps": cam.fps, "resolution": cam.resolution,
    }


# ============================================================
# SETTINGS
# ============================================================

@app.get("/api/settings")
def get_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return get_settings_for_site(db, current_user.site_id)


# ── A: auth + admin added ──
@app.put("/api/settings")
async def update_settings(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can change settings")
    body = await request.json()
    save_settings_for_site(db, current_user.site_id, body)
    return {"status": "saved", "settings": get_settings_for_site(db, current_user.site_id)}


# ============================================================
# DANGER ZONE
# ============================================================

# ── A: auth + admin added ──
@app.post("/api/danger/flush-alerts")
def flush_alerts(current_user: User = Depends(get_current_user)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can flush alerts")
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


# ── A: auth + admin added ──
@app.post("/api/danger/reset-tracks")
def reset_tracks(current_user: User = Depends(get_current_user)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can reset tracks")
    return {"status": "tracks_reset", "note": "Restart run_pipeline.py to fully reset ByteTrack state"}


# ============================================================
# ANALYTICS
# ============================================================

def get_date_range(from_date: str = None, to_date: str = None):
    if not from_date:
        from_dt = datetime.utcnow() - timedelta(days=7)
    else:
        from_dt = datetime.strptime(from_date, "%Y-%m-%d")
    if not to_date:
        to_dt = datetime.utcnow()
    else:
        to_dt = datetime.strptime(to_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
    return from_dt, to_dt


def get_incidents_in_range(db: Session, site_id: int, from_dt: datetime, to_dt: datetime):
    return db.query(Incident).filter(
        Incident.site_id == site_id,
        Incident.timestamp >= from_dt,
        Incident.timestamp <= to_dt
    ).all()


@app.get("/api/analytics/incidents-over-time")
def incidents_over_time(
    period: str = "day",
    from_date: str = None,
    to_date: str = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    from_dt, to_dt = get_date_range(from_date, to_date)
    incidents = get_incidents_in_range(db, current_user.site_id, from_dt, to_dt)
    counts = defaultdict(int)
    for inc in incidents:
        if inc.timestamp:
            if period == "day":
                key = inc.timestamp.strftime("%Y-%m-%d")
            elif period == "week":
                key = inc.timestamp.strftime("%Y-W%W")
            else:
                key = inc.timestamp.strftime("%Y-%m")
            counts[key] += 1
    result = []
    cur = from_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    while cur <= to_dt:
        if period == "day":
            key = cur.strftime("%Y-%m-%d")
            cur += timedelta(days=1)
        elif period == "week":
            key = cur.strftime("%Y-W%W")
            cur += timedelta(weeks=1)
        else:
            key = cur.strftime("%Y-%m")
            if cur.month == 12:
                cur = cur.replace(year=cur.year + 1, month=1)
            else:
                cur = cur.replace(month=cur.month + 1)
        result.append({"date": key, "count": counts.get(key, 0)})
    return result


@app.get("/api/analytics/incidents-by-rule")
def incidents_by_rule(
    from_date: str = None,
    to_date: str = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    from_dt, to_dt = get_date_range(from_date, to_date)
    incidents = get_incidents_in_range(db, current_user.site_id, from_dt, to_dt)
    counts = defaultdict(lambda: {"count": 0, "severity": "high"})
    for inc in incidents:
        rule_name = inc.violation_type or "unknown"
        counts[rule_name]["count"] += 1
        counts[rule_name]["severity"] = inc.severity or "high"
    result = [{"rule_name": k, "count": v["count"], "severity": v["severity"]} for k, v in counts.items()]
    result.sort(key=lambda x: x["count"], reverse=True)
    return result[:10]


@app.get("/api/analytics/incidents-by-hour")
def incidents_by_hour(
    from_date: str = None,
    to_date: str = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    from_dt, to_dt = get_date_range(from_date, to_date)
    incidents = get_incidents_in_range(db, current_user.site_id, from_dt, to_dt)
    counts = defaultdict(int)
    for inc in incidents:
        if inc.timestamp:
            counts[inc.timestamp.hour] += 1
    return [{"hour": h, "count": counts.get(h, 0)} for h in range(24)]


@app.get("/api/analytics/false-positive-rate")
def false_positive_rate(
    from_date: str = None,
    to_date: str = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    from_dt, to_dt = get_date_range(from_date, to_date)
    incidents = get_incidents_in_range(db, current_user.site_id, from_dt, to_dt)
    rule_data = defaultdict(lambda: {"tp": 0, "fp": 0})
    for inc in incidents:
        rule_name = inc.violation_type or "unknown"
        if inc.review_status == "false_positive":
            rule_data[rule_name]["fp"] += 1
        else:
            rule_data[rule_name]["tp"] += 1
    result = []
    for rule_name, data in rule_data.items():
        total = data["tp"] + data["fp"]
        rate = round((data["fp"] / total) * 100, 1) if total > 0 else 0.0
        result.append({"rule_name": rule_name, "tp_count": data["tp"], "fp_count": data["fp"], "total": total, "rate": rate})
    result.sort(key=lambda x: x["rate"], reverse=True)
    return result


# ============================================================
# EXPORT (CSV + PDF)
# ============================================================

@app.get("/api/export/incidents")
def export_incidents(
    format: str = "csv",
    from_date: str = None,
    to_date: str = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can export data")
    from_dt, to_dt = get_date_range(from_date, to_date)
    incidents = get_incidents_in_range(db, current_user.site_id, from_dt, to_dt)
    incidents.sort(key=lambda x: x.timestamp or datetime.min, reverse=True)
    site_settings = get_settings_for_site(db, current_user.site_id)
    site_name = site_settings["platform"].get("site_name", "Site").replace(" ", "_").replace("—", "-")
    from_str = from_dt.strftime("%Y-%m-%d")
    to_str = to_dt.strftime("%Y-%m-%d")
    filename_base = f"omnix_report_{site_name}_{from_str}_to_{to_str}"

    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["id", "timestamp", "rule_name", "severity", "zone", "camera", "alert_message", "review_status", "reviewed_by", "screenshot_url"])
        for inc in incidents:
            screenshot_url = ""
            if inc.screenshot_path:
                filename = inc.screenshot_path.replace("incidents/", "")
                screenshot_url = f"{PUBLIC_BASE_URL}/screenshots/{filename}"
            writer.writerow([inc.id, inc.timestamp.isoformat() if inc.timestamp else "", inc.violation_type or "", inc.severity or "", inc.zone or "", f"Camera {inc.camera_id or 1}", inc.alert_message or "", inc.review_status or "", inc.reviewed_by or "", screenshot_url])
        output.seek(0)
        return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{filename_base}.csv"'})

    elif format == "pdf":
        try:
            from reportlab.lib.pagesizes import landscape, A4
            from reportlab.lib import colors
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import cm
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
            from reportlab.lib.enums import TA_CENTER, TA_LEFT
        except ImportError:
            raise HTTPException(status_code=500, detail="reportlab not installed.")

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), rightMargin=1.5*cm, leftMargin=1.5*cm, topMargin=2*cm, bottomMargin=2*cm)
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle("Title", parent=styles["Heading1"], fontSize=18, alignment=TA_CENTER, textColor=colors.HexColor("#1a1a2e"), spaceAfter=6)
        subtitle_style = ParagraphStyle("Sub", parent=styles["Normal"], fontSize=10, alignment=TA_CENTER, textColor=colors.HexColor("#6366f1"), spaceAfter=4)
        section_style = ParagraphStyle("Section", parent=styles["Heading2"], fontSize=13, textColor=colors.HexColor("#1a1a2e"), spaceBefore=14, spaceAfter=6)
        cell_style = ParagraphStyle("Cell", parent=styles["Normal"], fontSize=8, textColor=colors.HexColor("#374151"), wordWrap="CJK")
        story = []
        story.append(Paragraph("OMNIX Safety Report", title_style))
        site_display = site_settings["platform"].get("site_name", "Site A")
        story.append(Paragraph(f"{site_display} · {from_str} to {to_str}", subtitle_style))
        story.append(Paragraph(f"Generated for {current_user.name or current_user.email} on {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}", subtitle_style))
        story.append(Spacer(1, 0.5*cm))
        story.append(Paragraph("Summary", section_style))
        total = len(incidents)
        sev_counts = defaultdict(int)
        rule_counts = defaultdict(int)
        for inc in incidents:
            sev_counts[inc.severity or "unknown"] += 1
            rule_counts[inc.violation_type or "unknown"] += 1
        days_diff = max((to_dt - from_dt).days, 1)
        avg_per_day = round(total / days_diff, 1)
        summary_data = [["Metric", "Value"], ["Total Incidents", str(total)], ["Date Range", f"{from_str} to {to_str}"], ["Avg per Day", str(avg_per_day)], ["Critical", str(sev_counts.get("critical", 0))], ["High", str(sev_counts.get("high", 0))], ["Medium", str(sev_counts.get("medium", 0))], ["Unique Rules Triggered", str(len(rule_counts))]]
        summary_table = Table(summary_data, colWidths=[6*cm, 6*cm])
        summary_table.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#6366f1")), ("TEXTCOLOR", (0,0), (-1,0), colors.white), ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"), ("FONTSIZE", (0,0), (-1,0), 10), ("ALIGN", (0,0), (-1,-1), "LEFT"), ("FONTSIZE", (0,1), (-1,-1), 9), ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.HexColor("#f9fafb"), colors.white]), ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#e5e7eb")), ("LEFTPADDING", (0,0), (-1,-1), 8), ("RIGHTPADDING", (0,0), (-1,-1), 8), ("TOPPADDING", (0,0), (-1,-1), 5), ("BOTTOMPADDING", (0,0), (-1,-1), 5)]))
        story.append(summary_table)
        story.append(Spacer(1, 0.5*cm))
        if rule_counts:
            story.append(Paragraph("Incidents by Rule", section_style))
            rule_data = [["Rule", "Count"]]
            for rule, count in sorted(rule_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
                rule_data.append([rule.replace("_", " ").title(), str(count)])
            rule_table = Table(rule_data, colWidths=[10*cm, 4*cm])
            rule_table.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#6366f1")), ("TEXTCOLOR", (0,0), (-1,0), colors.white), ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"), ("FONTSIZE", (0,0), (-1,0), 10), ("ALIGN", (1,0), (1,-1), "CENTER"), ("FONTSIZE", (0,1), (-1,-1), 9), ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.HexColor("#f9fafb"), colors.white]), ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#e5e7eb")), ("LEFTPADDING", (0,0), (-1,-1), 8), ("RIGHTPADDING", (0,0), (-1,-1), 8), ("TOPPADDING", (0,0), (-1,-1), 5), ("BOTTOMPADDING", (0,0), (-1,-1), 5)]))
            story.append(rule_table)
            story.append(Spacer(1, 0.5*cm))
        story.append(PageBreak())
        story.append(Paragraph("Incident Log", section_style))
        page_w = landscape(A4)[0] - 3*cm
        col_widths = [page_w*0.05, page_w*0.13, page_w*0.18, page_w*0.08, page_w*0.13, page_w*0.10, page_w*0.23, page_w*0.10]
        table_data = [["ID", "Timestamp", "Rule", "Severity", "Zone", "Camera", "Message", "Status"]]
        for inc in incidents[:500]:
            table_data.append([str(inc.id), inc.timestamp.strftime("%Y-%m-%d %H:%M") if inc.timestamp else "", Paragraph((inc.violation_type or "").replace("_", " ").title(), cell_style), (inc.severity or "").capitalize(), Paragraph((inc.zone or "").replace("_", " ").title(), cell_style), f"Camera {inc.camera_id or 1}", Paragraph(inc.alert_message or "", cell_style), (inc.review_status or "pending").capitalize()])
        inc_table = Table(table_data, colWidths=col_widths, repeatRows=1)
        inc_table.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#1e1b4b")), ("TEXTCOLOR", (0,0), (-1,0), colors.white), ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"), ("FONTSIZE", (0,0), (-1,0), 9), ("ALIGN", (0,0), (-1,-1), "LEFT"), ("VALIGN", (0,0), (-1,-1), "MIDDLE"), ("FONTSIZE", (0,1), (-1,-1), 8), ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.HexColor("#f9fafb"), colors.white]), ("GRID", (0,0), (-1,-1), 0.3, colors.HexColor("#e5e7eb")), ("LEFTPADDING", (0,0), (-1,-1), 5), ("RIGHTPADDING", (0,0), (-1,-1), 5), ("TOPPADDING", (0,0), (-1,-1), 4), ("BOTTOMPADDING", (0,0), (-1,-1), 4)]))
        story.append(inc_table)

        def add_page_number(canvas, doc):
            canvas.saveState()
            canvas.setFont("Helvetica", 8)
            canvas.setFillColor(colors.HexColor("#6b7280"))
            canvas.drawCentredString(landscape(A4)[0] / 2, 1*cm, f"Page {doc.page} — OMNIX Safety Report — {site_display}")
            canvas.restoreState()

        doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
        buffer.seek(0)
        return StreamingResponse(buffer, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{filename_base}.pdf"'})

    else:
        raise HTTPException(status_code=400, detail="format must be 'csv' or 'pdf'")
