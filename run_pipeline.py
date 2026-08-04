import json
import cv2
import numpy as np
from datetime import datetime
from pathlib import Path
from ultralytics import YOLO

# DB imports
import os
from dotenv import load_dotenv
load_dotenv()

from db.session import SessionLocal
from db.models import Incident, Rule, Site, Camera as CameraModel

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER or "omnix-alerts@localhost")
ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO")  # comma-separated list

EMAIL_SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}

# ============================================================
# CONFIG LOADING
# ============================================================
with open('pipeline_config.json', 'r') as f:
    config = json.load(f)

# ── Part 1: Read persistence_frames from config (default 5) ──
PERSISTENCE_FRAMES = int(config.get('persistence_frames', 5))

# ── Task 3: Read alert_cooldown_frames and detection_confidence from config
# (previously hardcoded 150 and 0.5). Settings page → apply_rule() writes these
# into pipeline_config.json; this is where the pipeline actually reads them. ──
ALERT_COOLDOWN_FRAMES = int(config.get('alert_cooldown_frames', 150))
GLOBAL_DETECTION_CONFIDENCE = float(config.get('detection_confidence', 0.5))

# ── Task C fold-in: email settings, same DB-Settings → pipeline_config.json → pipeline reads it pattern ──
EMAIL_NOTIFICATIONS_ENABLED = bool(config.get('email_notifications_enabled', False))
EMAIL_SEVERITY_THRESHOLD = config.get('email_severity_threshold', 'high')

print(f"\n{'='*60}")
print(f"Pipeline: {config['pipeline_id']}")
print(f"Description: {config['description']}")
print(f"Zones: {len(config.get('zones', []))}")
print(f"Rules: {len(config.get('rules', []))}")
print(f"Persistence frames: {PERSISTENCE_FRAMES}")
print(f"Alert cooldown frames: {ALERT_COOLDOWN_FRAMES}")
print(f"Global detection confidence: {GLOBAL_DETECTION_CONFIDENCE}")
print(f"Email notifications: {'enabled (threshold=' + EMAIL_SEVERITY_THRESHOLD + ')' if EMAIL_NOTIFICATIONS_ENABLED else 'disabled'}")
print(f"{'='*60}\n")

# ============================================================
# LOAD DB REFERENCES
# ============================================================
import argparse

_arg_parser = argparse.ArgumentParser()
_arg_parser.add_argument("--camera_id", type=int, default=1)
_args, _ = _arg_parser.parse_known_args()
TARGET_CAMERA_ID = _args.camera_id


def get_db_refs(target_camera_id: int):
    try:
        db = SessionLocal()
        site = db.query(Site).first()
        camera = db.query(CameraModel).filter(CameraModel.id == target_camera_id).first()
        if camera is None:
            print(f"[WARN] camera_id={target_camera_id} not found in DB, falling back to first camera row")
            camera = db.query(CameraModel).first()
        rule = db.query(Rule).filter(
            Rule.pipeline_id == config['pipeline_id'],
            Rule.status == 'active'
        ).first()
        if not rule:
            rule = db.query(Rule).filter(Rule.status == 'active').first()
        source = camera.source if (camera and camera.source and camera.source != "default") else None
        resolved_camera_id = camera.id if camera else None
        db.close()
        return (
            site.id if site else None,
            resolved_camera_id,
            rule.id if rule else None,
            source,
        )
    except Exception as e:
        print(f"[WARN] Could not get DB refs: {e}")
        return None, None, None, None

site_id, camera_id, rule_id, camera_source = get_db_refs(TARGET_CAMERA_ID)
print(f"[DB] site_id={site_id}, camera_id={camera_id}, rule_id={rule_id}, camera_source={camera_source}")

# ============================================================
# MODEL REGISTRY — load registry and lazy-load only needed models
# ============================================================
with open('model_registry.json', 'r') as f:
    registry = json.load(f)

print(f"[INFO] Model registry loaded: {list(registry.keys())}")

# ── Part 2: Helper to get per-model conf_threshold.
# ── Task 3: fallback now comes from GLOBAL_DETECTION_CONFIDENCE (Settings),
# not a hardcoded 0.5, unless a model has its own conf_threshold in the registry. ──
def get_model_conf(model_name: str, fallback: float = GLOBAL_DETECTION_CONFIDENCE) -> float:
    entry = registry.get(model_name, {})
    return float(entry.get('conf_threshold', entry.get('confidence', fallback)))

def load_model_from_registry(model_name: str) -> YOLO | None:
    if model_name not in registry:
        print(f"  [WARN] '{model_name}' not in registry")
        return None
    entry = registry[model_name]
    model_type = entry.get("type", "custom")

    if model_type == "coco_default":
        model_path = entry.get("model", "yolov8n.pt")
        if not Path(model_path).exists():
            print(f"  [SKIP] {model_name}: base model {model_path} not found")
            return None
        try:
            m = YOLO(model_path)
            print(f"  [OK] Loaded {model_name} (COCO class {entry.get('class_id')}) from {model_path} [conf={get_model_conf(model_name)}]")
            return m
        except Exception as e:
            print(f"  [FAIL] {model_name}: {e}")
            return None

    elif model_type == "custom":
        weights = entry.get("weights", "")
        if not Path(weights).exists():
            print(f"  [SKIP] {model_name}: weights not found at {weights}")
            return None
        try:
            m = YOLO(weights)
            print(f"  [OK] Loaded {model_name} from {weights} [conf={get_model_conf(model_name)}]")
            return m
        except Exception as e:
            print(f"  [FAIL] {model_name}: {e}")
            return None

    return None

# Determine which models are needed
needed_models = set()
for rule in config.get('rules', []):
    for gear in rule.get('required', []):
        needed_models.add(gear)
    # ── object_in_zone: the target object model must be loaded too ──
    if rule.get('target'):
        needed_models.add(rule['target'])
for name in config.get('models', {}).keys():
    needed_models.add(name)

print(f"\n[INFO] Models needed by pipeline: {needed_models}")
print(f"[INFO] Loading only required models (lazy loading)...")

models = {}
for model_name in needed_models:
    m = load_model_from_registry(model_name)
    if m is not None:
        models[model_name] = m

base_entry   = registry.get("person", {})
base_model_path = base_entry.get("model", "yolov8n.pt")
# ── Part 2 / Task 3: use conf_threshold for person model, falling back to the
# Settings-driven GLOBAL_DETECTION_CONFIDENCE instead of a hardcoded 0.5 ──
base_conf    = get_model_conf("person", fallback=GLOBAL_DETECTION_CONFIDENCE)
base_model   = YOLO(base_model_path)
print(f"\n[OK] Loaded base YOLO for person detection (conf_threshold={base_conf})")
print(f"[INFO] Total models loaded: {list(models.keys())}\n")

# ============================================================
# HELPER: write incident to DB + JSON fallback
# ============================================================
INCIDENTS_FILE = Path('incidents.json')

# ============================================================
# HELPER: email notification for a new incident
# ============================================================
def send_incident_email(incident: dict):
    """Sends an email for a new incident, if SMTP is configured, email is enabled
    in Settings, and the incident's severity meets the configured threshold.
    Fires from the same single trigger point as DB/JSON incident writes — one
    event, one place — rather than a separate notification pipeline."""
    if not SMTP_HOST or not ALERT_EMAIL_TO:
        return  # Not configured — silently skip, no need to log every incident
    if not EMAIL_NOTIFICATIONS_ENABLED:
        return

    incident_severity = config.get("alert", {}).get("severity", "medium")
    if EMAIL_SEVERITY_ORDER.get(incident_severity, 1) < EMAIL_SEVERITY_ORDER.get(EMAIL_SEVERITY_THRESHOLD, 2):
        return

    recipients = [r.strip() for r in ALERT_EMAIL_TO.split(",") if r.strip()]
    if not recipients:
        return

    screenshot_link = f"{PUBLIC_BASE_URL}/{incident['screenshot_path']}"
    violation_label = (incident.get('violation') or 'violation').replace('_', ' ')
    subject = f"[OMNIX] {incident_severity.upper()} violation: {violation_label}"
    body = (
        f"A new violation was detected by OMNIX.\n\n"
        f"Violation: {violation_label}\n"
        f"Zone: {incident.get('zone', 'unknown')}\n"
        f"Camera: {incident.get('camera', 'unknown')}\n"
        f"Time: {incident.get('timestamp', '')}\n"
        f"Severity: {incident_severity}\n\n"
        f"Screenshot: {screenshot_link}\n\n"
        f"This is an automated message from OMNIX Safety Monitoring."
    )

    msg = MIMEMultipart()
    msg["From"] = SMTP_FROM
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.starttls()
            if SMTP_USER and SMTP_PASSWORD:
                server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM, recipients, msg.as_string())
        print(f"  [EMAIL] Sent alert email to {', '.join(recipients)}")
    except Exception as e:
        print(f"  [WARN] Failed to send alert email: {e}")


def build_detected_objects(result, extra_objects: list = None) -> list:
    """
    Builds the full list of everything detected this frame — every currently
    tracked person (ByteTrack ID + bbox), plus any target-model object boxes
    passed in via extra_objects (e.g. the spill/fire that triggered an
    object_in_zone or person_near_object rule). Previously only the single
    violator's bbox was ever stored on an incident; this is the foundation for
    the Incident Inspector feature (click a person in the list -> highlight
    them in the frame) — can't build that UI until this data actually exists.
    """
    detected = []
    if result.boxes is not None and result.boxes.id is not None:
        # confidence sits in result.boxes.conf, parallel to .xyxy and .id
        confs = result.boxes.conf.cpu().numpy() if result.boxes.conf is not None else None
        for i, (box, tid) in enumerate(zip(result.boxes.xyxy.cpu().numpy(), result.boxes.id.cpu().numpy())):
            x1, y1, x2, y2 = box
            detected.append({
                "type": "person",
                "track_id": int(tid),
                "bbox": [round(float(x1), 1), round(float(y1), 1), round(float(x2), 1), round(float(y2), 1)],
                "confidence": round(float(confs[i]), 3) if confs is not None else None,
            })
    if extra_objects:
        # TODO(fast-follow): confidence for object-type detections (spill,
        # fire, etc.) isn't threaded through yet — hits/obj_boxes at the call
        # sites only carry bbox arrays, and object_memory caches boxes across
        # frames without confidence, so wiring this up safely needs a small
        # refactor of the caching path rather than a quick change here.
        for label, box in extra_objects:
            x1, y1, x2, y2 = box
            detected.append({
                "type": label,
                "track_id": None,
                "bbox": [round(float(x1), 1), round(float(y1), 1), round(float(x2), 1), round(float(y2), 1)],
                "confidence": None,
            })
    return detected


def append_incident(incident: dict):
    if rule_id and site_id:
        try:
            db = SessionLocal()
            db_incident = Incident(
                 rule_id=incident.get("rule_db_id") or rule_id,
                camera_id=camera_id,
                site_id=site_id,
                timestamp=datetime.fromisoformat(incident["timestamp"]),
                frame_number=incident.get("frame"),
                person_track_id=incident.get("person_id"),
                violation_type=incident.get("violation"),
                detected_objects=incident.get("detected_objects"),
                missing_gear=incident.get("missing_gear") or None,
                zone=incident.get("zone"),
                bbox=incident.get("bbox"),
                screenshot_path=incident.get("screenshot_path"),
                severity=config.get("alert", {}).get("severity", "medium"),
                alert_message=incident.get("alert_message"),
                reviewed=False,
            )
            db.add(db_incident)
            db.commit()
            db.close()
            print(f"  [DB] Incident saved to PostgreSQL")
        except Exception as e:
            print(f"  [WARN] DB write failed: {e}, falling back to JSON")
            _append_json(incident)
    else:
        _append_json(incident)
    send_incident_email(incident)


def _append_json(incident: dict):
    if INCIDENTS_FILE.exists():
        try:
            with open(INCIDENTS_FILE, 'r') as f:
                incidents = json.load(f)
        except:
            incidents = []
    else:
        incidents = []
    incidents.append(incident)
    tmp = INCIDENTS_FILE.with_suffix('.tmp')
    with open(tmp, 'w') as f:
        json.dump(incidents, f, indent=2)
    tmp.replace(INCIDENTS_FILE)


# ============================================================
# HELPER: point in polygon (ray casting)
# ============================================================
def point_in_polygon(x: float, y: float, poly) -> bool:
    if not poly or len(poly) < 3:
        return False
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i][0], poly[i][1]
        xj, yj = poly[j][0], poly[j][1]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi):
            inside = not inside
        j = i
    return inside


# ============================================================
# HELPER: bbox overlap
# ============================================================
def bbox_overlap(box1, box2):
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])
    if x2 < x1 or y2 < y1:
        return 0.0
    intersection = (x2 - x1) * (y2 - y1)
    box2_area = (box2[2] - box2[0]) * (box2[3] - box2[1])
    if box2_area == 0:
        return 0.0
    return intersection / box2_area


def check_required_gear(person_bbox, frame, required_gear, loaded_models):
    missing = []
    for gear_name in required_gear:
        if gear_name not in loaded_models:
            print(f"  [WARN] Required gear '{gear_name}' not loaded, skipping")
            continue
        entry = registry.get(gear_name, {})
        # ── Part 2 / Task 3: use conf_threshold per gear model, falling back
        # to Settings-driven GLOBAL_DETECTION_CONFIDENCE instead of hardcoded 0.5 ──
        conf = get_model_conf(gear_name, fallback=GLOBAL_DETECTION_CONFIDENCE)

        if entry.get("type") == "coco_default":
            class_id = entry.get("class_id", 0)
            gear_results = loaded_models[gear_name](frame, verbose=False,
                                                     conf=conf, classes=[class_id])
        else:
            gear_results = loaded_models[gear_name](frame, verbose=False, conf=conf)

        has_gear = False
        if gear_results[0].boxes is not None and len(gear_results[0].boxes) > 0:
            for gear_box in gear_results[0].boxes.xyxy.cpu().numpy():
                if bbox_overlap(person_bbox, gear_box) > 0.3:
                    has_gear = True
                    break
        if not has_gear:
            missing.append(gear_name)
    return missing


# ============================================================
# BUILD ZONE LOOKUP
# ============================================================
zones_map = {}
for zone in config.get('zones', []):
    coords = zone['coords']
    zones_map[zone['name']] = {
        'x_min': min(p[0] for p in coords),
        'x_max': max(p[0] for p in coords),
        'y_min': min(p[1] for p in coords),
        'y_max': max(p[1] for p in coords),
        'coords': coords,
        'source': zone.get('source', 'llm_default'),
        'poly': coords,
    }

rules = config.get('rules', [])
print(f"Active zones: {list(zones_map.keys())}")
print(f"Active rules:")
for r in rules:
    print(f"  - {r['type']} in {r.get('zone', 'anywhere')} (required: {r.get('required', [])})")
print()

# ============================================================
# PIPELINE STATE
# ============================================================
Path('incidents').mkdir(exist_ok=True)
if INCIDENTS_FILE.exists():
    INCIDENTS_FILE.unlink()

incident_count = 0
RUN_ID = datetime.now().strftime("%Y%m%d_%H%M%S")

# ── Occlusion fix: remember each proximity target's last-seen boxes for a
# short window. A puddle doesn't walk away — if detection drops the moment
# a person steps INTO it (occlusion), proximity must still fire. ──
OBJECT_MEMORY_FRAMES = 50
object_memory = {}  # rule_idx -> {"boxes": [...], "last_seen": frame_idx}

# ── Part 1: Cooldown tracker (existing) ──
active_violations = {}

# ── Part 1: Streak counter — tracks consecutive violation frames per (person_id, rule_idx) ──
# streak_counters[key] = number of consecutive frames with violation
streak_counters = {}

video = camera_source if camera_source else 'mega_cctv_v2.mp4'
print(f"Processing {video} (camera_id={camera_id})...")

# ── RTSP Phase 2: know whether this is a live stream (rtsp://) vs a finite file ──
is_live_source = isinstance(video, str) and video.startswith("rtsp://")

_cap = cv2.VideoCapture(video)
ORIG_W = int(_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
ORIG_H = int(_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
_cap.release()
print(f"[INFO] Original video resolution: {ORIG_W}x{ORIG_H}\n")

# ── Issue #26 fix: zone coords are now stored normalized (0-1, relative to
# frame size), so scaling to native resolution is a direct multiply — no more
# assuming the drawing canvas was 854x480. SCALE_X/SCALE_Y below remain for
# proximity_px only (person_near_object's threshold is still spec'd at 854x480,
# a separate concern from zone placement). ──
SNAP_W, SNAP_H = 854, 480
SCALE_X = (ORIG_W / SNAP_W) if ORIG_W else 1.0
SCALE_Y = (ORIG_H / SNAP_H) if ORIG_H else 1.0
PROXIMITY_SCALE = (SCALE_X + SCALE_Y) / 2
for zn, zd in zones_map.items():
    if zd['source'] == 'user_drawn' and ORIG_W and ORIG_H:
        zd['poly'] = [[p[0] * ORIG_W, p[1] * ORIG_H] for p in zd['coords']]
        zd['x_min'] = min(p[0] for p in zd['poly'])
        zd['x_max'] = max(p[0] for p in zd['poly'])
        zd['y_min'] = min(p[1] for p in zd['poly'])
        zd['y_max'] = max(p[1] for p in zd['poly'])
        print(f"[ZONE] '{zn}' normalized polygon scaled to native res ({len(zd['poly'])} points)")
    else:
        zd['poly'] = zd['coords']

# ============================================================
# MAIN PROCESSING LOOP
# ============================================================
results = base_model.track(
    source=video,
    persist=True,
    classes=[0],
    stream=True,
    conf=base_conf,
    verbose=False
)

# ── RTSP Phase 2: wrap the loop so we can tell a real crash / an unexpected
# stream drop apart from a normal file reaching its end, and log loudly
# instead of silently exiting. Loop body itself is unchanged. ──
try:
    for frame_idx, result in enumerate(results):

        # ============================================================
        # ── object_in_zone rules: evaluated PER FRAME, independent of
        # people. "Alert when fire is detected in site area" fires on
        # the fire itself — no person required. ──
        # ============================================================
        for rule_idx, rule in enumerate(rules):
            if rule.get('type') != 'object_in_zone':
                continue
            target = rule.get('target') or (rule.get('required') or [None])[0]
            zone_name = rule.get('zone', '')
            if not target or target not in models or zone_name not in zones_map:
                continue
            zone = zones_map[zone_name]
            obj_key = ('obj', rule_idx)

            conf = get_model_conf(target, fallback=GLOBAL_DETECTION_CONFIDENCE)
            entry = registry.get(target, {})
            if entry.get("type") == "coco_default":
                obj_results = models[target](result.orig_img, verbose=False,
                                             conf=conf, classes=[entry.get("class_id", 0)])
            else:
                obj_results = models[target](result.orig_img, verbose=False, conf=conf)

            hits = []
            if obj_results[0].boxes is not None and len(obj_results[0].boxes) > 0:
                for ob in obj_results[0].boxes.xyxy.cpu().numpy():
                    ocx = (ob[0] + ob[2]) / 2
                    ocy = (ob[1] + ob[3]) / 2
                    if point_in_polygon(ocx, ocy, zone['poly']):
                        hits.append(ob)

            if hits:
                streak_counters[obj_key] = streak_counters.get(obj_key, 0) + 1
                current_streak = streak_counters[obj_key]
                # ── Per-rule sensitivity: rule may carry its own persistence ──
                rule_persistence = int(rule.get('persistence_frames') or PERSISTENCE_FRAMES)
                if current_streak >= rule_persistence and obj_key not in active_violations:
                    incident_count += 1
                    incident_id = f"inc_{RUN_ID}_{incident_count:04d}"
                    screenshot_path = f"incidents/{incident_id}.jpg"
                    orig_frame = result.orig_img.copy()
                    for ob in hits:
                        bx1, by1, bx2, by2 = map(int, ob)
                        cv2.rectangle(orig_frame, (bx1, by1), (bx2, by2), (0, 0, 255), 2)
                        cv2.putText(orig_frame, target.upper(), (bx1 + 2, max(by1 - 6, 14)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
                    for zn, zd in zones_map.items():
                        color = (0, 255, 255) if zn == zone_name else (0, 180, 180)
                        pts = np.array(zd['poly'], dtype=np.int32).reshape((-1, 1, 2))
                        cv2.polylines(orig_frame, [pts], isClosed=True, color=color, thickness=2)
                        cv2.putText(orig_frame, zn.replace("_", " ").upper(),
                                    (int(zd['x_min']) + 4, int(zd['y_min']) + 18),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)
                    cv2.putText(orig_frame, f"{target.upper()} DETECTED streak={current_streak}",
                                (10, orig_frame.shape[0] - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2)
                    cv2.imwrite(screenshot_path, orig_frame)

                    fb = hits[0]
                    incident = {
                        "id":              incident_id,
                        "timestamp":       datetime.now().isoformat(),
                        "frame":           frame_idx,
                        "camera":          video,
                        "person_id":       None,
                        "violation":       f"{target}_detected",
                        "missing_gear":    [],
                        "zone":            zone_name,
                        "rule_index":      rule_idx,
                        "bbox":            [float(fb[0]), float(fb[1]), float(fb[2]), float(fb[3])],
                        "screenshot_path": screenshot_path,
                        "rule_type":       "object_in_zone",
                        "alert_message":   config['alert']['message'],
                        "streak_frames":   current_streak,
                        "rule_db_id":      rule.get("rule_db_id"),
                        "detected_objects": build_detected_objects(result, [(target, ob) for ob in hits]),
                    }
                    append_incident(incident)
                    print(f"Frame {frame_idx}: {target.upper()} | rule[{rule_idx}] object_in_zone in {zone_name}"
                          + f" | streak={current_streak} → {incident_id} [FIRED]")
                    active_violations[obj_key] = frame_idx
            else:
                if obj_key in streak_counters:
                    del streak_counters[obj_key]
                if obj_key in active_violations:
                    if frame_idx - active_violations[obj_key] > ALERT_COOLDOWN_FRAMES:
                        del active_violations[obj_key]

        # ============================================================
        # ── person_near_object rules: PER-FRAME, checks pixel distance from
        # each tracked person's bbox bottom-center to the nearest edge of the
        # target object's bbox (e.g. "person near spill"). Honest limitation:
        # pixel distance ≠ real meters (no camera calibration) — acceptable
        # for POC, calibration is a someday-item. ──
        # ============================================================
        has_people_this_frame = result.boxes is not None and result.boxes.id is not None
        person_boxes_this_frame = (
            list(zip(result.boxes.xyxy.cpu().numpy(), result.boxes.id.cpu().numpy()))
            if has_people_this_frame else []
        )

        for rule_idx, rule in enumerate(rules):
            if rule.get('type') != 'person_near_object':
                continue
            target = rule.get('target')
            if not target or target not in models or not person_boxes_this_frame:
                continue

            conf = get_model_conf(target, fallback=GLOBAL_DETECTION_CONFIDENCE)
            entry = registry.get(target, {})
            if entry.get("type") == "coco_default":
                obj_results = models[target](result.orig_img, verbose=False,
                                             conf=conf, classes=[entry.get("class_id", 0)])
            else:
                obj_results = models[target](result.orig_img, verbose=False, conf=conf)

            obj_boxes = []
            if obj_results[0].boxes is not None and len(obj_results[0].boxes) > 0:
                obj_boxes = list(obj_results[0].boxes.xyxy.cpu().numpy())

            # ── Occlusion fix: live detection refreshes memory; a dropout
            # within OBJECT_MEMORY_FRAMES falls back to the last-seen boxes
            # (person standing IN the spill hides it from the detector —
            # exactly the moment the alert matters most). ──
            if obj_boxes:
                object_memory[rule_idx] = {"boxes": obj_boxes, "last_seen": frame_idx}
            else:
                mem = object_memory.get(rule_idx)
                if mem and frame_idx - mem["last_seen"] <= OBJECT_MEMORY_FRAMES:
                    obj_boxes = mem["boxes"]

            proximity_px_native = float(rule.get('proximity_px', 120)) * PROXIMITY_SCALE

            for pbox, ptid in person_boxes_this_frame:
                person_id = int(ptid)
                px1, py1, px2, py2 = pbox
                person_center_x = (px1 + px2) / 2
                person_bottom_y = py2  # bottom-center, same convention as zone rules

                cooldown_key = (rule_idx, person_id)

                # nearest-edge distance from person's bottom-center to each object bbox
                nearest_obj = None
                nearest_dist = float('inf')
                for ob in obj_boxes:
                    ox1, oy1, ox2, oy2 = ob
                    dx = max(ox1 - person_center_x, 0, person_center_x - ox2)
                    dy = max(oy1 - person_bottom_y, 0, person_bottom_y - oy2)
                    dist = (dx ** 2 + dy ** 2) ** 0.5
                    if dist < nearest_dist:
                        nearest_dist = dist
                        nearest_obj = ob

                if nearest_obj is not None and nearest_dist < proximity_px_native:
                    streak_counters[cooldown_key] = streak_counters.get(cooldown_key, 0) + 1
                    current_streak = streak_counters[cooldown_key]

                    # ── Per-rule sensitivity ──
                    rule_persistence = int(rule.get('persistence_frames') or PERSISTENCE_FRAMES)
                    if current_streak >= rule_persistence and cooldown_key not in active_violations:
                        incident_count += 1
                        incident_id = f"inc_{RUN_ID}_{incident_count:04d}"
                        screenshot_path = f"incidents/{incident_id}.jpg"
                        orig_frame = result.orig_img.copy()

                        # box the violating person — blue, same convention as other person boxes
                        bx1, by1, bx2, by2 = map(int, pbox)
                        cv2.rectangle(orig_frame, (bx1, by1), (bx2, by2), (255, 100, 0), 2)
                        label = f"id:{person_id} person"
                        (lw, lh), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
                        cv2.rectangle(orig_frame, (bx1, by1 - lh - 8), (bx1 + lw + 4, by1), (255, 100, 0), -1)
                        cv2.putText(orig_frame, label, (bx1 + 2, by1 - 4),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)

                        # box the target object — red, same convention as object_in_zone's target color
                        ox1, oy1, ox2, oy2 = map(int, nearest_obj)
                        cv2.rectangle(orig_frame, (ox1, oy1), (ox2, oy2), (0, 0, 255), 2)
                        cv2.putText(orig_frame, target.upper(), (ox1 + 2, max(oy1 - 6, 14)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

                        cv2.putText(orig_frame, f"NEAR {target.upper()} streak={current_streak}",
                                    (10, orig_frame.shape[0] - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2)
                        cv2.imwrite(screenshot_path, orig_frame)

                        incident = {
                            "id":              incident_id,
                            "timestamp":       datetime.now().isoformat(),
                            "frame":           frame_idx,
                            "camera":          video,
                            "person_id":       person_id,
                            "violation":       f"near_{target}",
                            "missing_gear":    [],
                            "zone":            rule.get('zone', ''),
                            "rule_index":      rule_idx,
                            "bbox":            [float(px1), float(py1), float(px2), float(py2)],
                            "screenshot_path": screenshot_path,
                            "rule_type":       "person_near_object",
                            "alert_message":   config['alert']['message'],
                            "streak_frames":   current_streak,
                            "rule_db_id":      rule.get("rule_db_id"),
                            "detected_objects": build_detected_objects(result, [(target, ob) for ob in obj_boxes]),
                        }
                        append_incident(incident)
                        print(f"Frame {frame_idx}: person #{person_id} | rule[{rule_idx}] person_near_object "
                              f"target={target} dist={nearest_dist:.0f}px | streak={current_streak} → {incident_id} [FIRED]")
                        active_violations[cooldown_key] = frame_idx
                else:
                    if cooldown_key in streak_counters:
                        del streak_counters[cooldown_key]
                    if cooldown_key in active_violations:
                        if frame_idx - active_violations[cooldown_key] > ALERT_COOLDOWN_FRAMES:
                            del active_violations[cooldown_key]

        # ============================================================
        # ── count_exceeded rules: PER-FRAME, per-zone person count vs threshold.
        # Previously a stub that fired for any single person present, regardless
        # of actual count. Real logic: tally how many currently-tracked people
        # are inside the rule's zone this frame, compare to the "count" field.
        # This is an aggregate/zone-level violation (no single culprit), so it's
        # keyed by rule_idx alone, not per-person like the other rule types. ──
        # ============================================================
        zone_person_counts: dict = {}
        for pbox, ptid in person_boxes_this_frame:
            pcx = (pbox[0] + pbox[2]) / 2
            pby = pbox[3]
            for zn, zd in zones_map.items():
                if point_in_polygon(pcx, pby, zd['poly']):
                    zone_person_counts[zn] = zone_person_counts.get(zn, 0) + 1

        for rule_idx, rule in enumerate(rules):
            if rule.get('type') != 'count_exceeded':
                continue
            zone_name = rule.get('zone', '')
            threshold = int(rule.get('count', 5))
            current_count = zone_person_counts.get(zone_name, 0)
            cooldown_key = (rule_idx, 'zone_count')  # aggregate violation, not person-specific

            if current_count > threshold:
                streak_counters[cooldown_key] = streak_counters.get(cooldown_key, 0) + 1
                current_streak = streak_counters[cooldown_key]
                rule_persistence = int(rule.get('persistence_frames') or PERSISTENCE_FRAMES)

                if current_streak >= rule_persistence and cooldown_key not in active_violations:
                    incident_count += 1
                    incident_id = f"inc_{RUN_ID}_{incident_count:04d}"
                    screenshot_path = f"incidents/{incident_id}.jpg"
                    orig_frame = result.orig_img.copy()

                    # box every currently-tracked person, so the crowd is visible in the evidence frame
                    if result.boxes is not None and result.boxes.id is not None:
                        for det_box, det_id in zip(result.boxes.xyxy.cpu().numpy(), result.boxes.id.cpu().numpy()):
                            dbx1, dby1, dbx2, dby2 = map(int, det_box)
                            cv2.rectangle(orig_frame, (dbx1, dby1), (dbx2, dby2), (255, 100, 0), 2)

                    for zn, zd in zones_map.items():
                        color = (0, 255, 255) if zn == zone_name else (0, 180, 180)
                        pts = np.array(zd['poly'], dtype=np.int32).reshape((-1, 1, 2))
                        cv2.polylines(orig_frame, [pts], isClosed=True, color=color, thickness=2)
                        cv2.putText(orig_frame, zn.replace("_", " ").upper(),
                                    (int(zd['x_min']) + 4, int(zd['y_min']) + 18),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)

                    cv2.putText(orig_frame, f"COUNT EXCEEDED: {current_count} > {threshold} streak={current_streak}",
                                (10, orig_frame.shape[0] - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2)
                    cv2.imwrite(screenshot_path, orig_frame)

                    incident = {
                        "id":              incident_id,
                        "timestamp":       datetime.now().isoformat(),
                        "frame":           frame_idx,
                        "camera":          video,
                        "person_id":       None,  # aggregate zone violation, no single culprit
                        "violation":       "count_exceeded",
                        "missing_gear":    [],
                        "zone":            zone_name,
                        "rule_index":      rule_idx,
                        "bbox":            None,
                        "screenshot_path": screenshot_path,
                        "rule_type":       "count_exceeded",
                        "alert_message":   config['alert']['message'],
                        "streak_frames":   current_streak,
                        "rule_db_id":      rule.get("rule_db_id"),
                        "detected_objects": build_detected_objects(result),
                    }
                    append_incident(incident)
                    print(f"Frame {frame_idx}: rule[{rule_idx}] count_exceeded in {zone_name} "
                          f"count={current_count} > {threshold} | streak={current_streak} → {incident_id} [FIRED]")
                    active_violations[cooldown_key] = frame_idx
            else:
                if cooldown_key in streak_counters:
                    del streak_counters[cooldown_key]
                if cooldown_key in active_violations:
                    if frame_idx - active_violations[cooldown_key] > ALERT_COOLDOWN_FRAMES:
                        del active_violations[cooldown_key]

        if result.boxes is None or result.boxes.id is None:
            continue

        for box, track_id in zip(result.boxes.xyxy.cpu().numpy(), result.boxes.id.cpu().numpy()):
            person_id = int(track_id)
            x1, y1, x2, y2 = box
            person_center_x = (x1 + x2) / 2
            person_bottom_y = y2

            for rule_idx, rule in enumerate(rules):
                zone_name = rule.get('zone', '')
                if zone_name not in zones_map:
                    continue

                zone          = zones_map[zone_name]
                rule_type     = rule.get('type', '')
                if rule_type in ('object_in_zone', 'person_near_object', 'count_exceeded'):
                    continue  # all three handled per-frame above, not in this per-person zone loop
                required_gear = rule.get('required', [])

                in_zone = point_in_polygon(person_center_x, person_bottom_y, zone['poly'])

                cooldown_key = (rule_idx, person_id)

                if not in_zone:
                    # ── Part 1: reset streak when person leaves zone ──
                    if cooldown_key in streak_counters:
                        del streak_counters[cooldown_key]
                    # cleanup stale cooldown — ── Task 3: uses ALERT_COOLDOWN_FRAMES from Settings ──
                    if cooldown_key in active_violations:
                        if frame_idx - active_violations[cooldown_key] > ALERT_COOLDOWN_FRAMES:
                            del active_violations[cooldown_key]
                    continue

                # Check violation condition
                violation_occurred = False
                violation_type     = rule_type
                missing_gear       = []

                if rule_type == "missing_in_zone" and required_gear:
                    missing_gear = check_required_gear(
                        (x1, y1, x2, y2), result.orig_img, required_gear, models
                    )
                    if missing_gear:
                        violation_occurred = True
                        violation_type = f"missing_{'_'.join(missing_gear)}"

                elif rule_type == "person_in_zone":
                    violation_occurred = True

                if violation_occurred:
                    # ── Part 1: increment streak counter ──
                    streak_counters[cooldown_key] = streak_counters.get(cooldown_key, 0) + 1
                    current_streak = streak_counters[cooldown_key]

                    # ── Per-rule sensitivity: rule-level persistence wins over global ──
                    rule_persistence = int(rule.get('persistence_frames') or PERSISTENCE_FRAMES)
                    if current_streak >= rule_persistence and cooldown_key not in active_violations:
                        incident_count += 1
                        incident_id     = f"inc_{RUN_ID}_{incident_count:04d}"
                        screenshot_path = f"incidents/{incident_id}.jpg"

                        # ── Part 1: screenshot taken at frame N (when incident fires) ──
                        orig_frame = result.orig_img.copy()

                        if result.boxes is not None and len(result.boxes) > 0:
                            for det_box, det_id in zip(
                                result.boxes.xyxy.cpu().numpy(),
                                result.boxes.id.cpu().numpy() if result.boxes.id is not None else [None] * len(result.boxes)
                            ):
                                bx1, by1, bx2, by2 = map(int, det_box)
                                det_id_val = int(det_id) if det_id is not None else 0
                                cv2.rectangle(orig_frame, (bx1, by1), (bx2, by2), (255, 100, 0), 2)
                                label = f"id:{det_id_val} person"
                                (lw, lh), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
                                cv2.rectangle(orig_frame, (bx1, by1 - lh - 8), (bx1 + lw + 4, by1), (255, 100, 0), -1)
                                cv2.putText(orig_frame, label, (bx1 + 2, by1 - 4),
                                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)

                        for zn, zd in zones_map.items():
                            color = (0, 255, 255) if zn == zone_name else (0, 180, 180)
                            pts = np.array(zd['poly'], dtype=np.int32).reshape((-1, 1, 2))
                            cv2.polylines(orig_frame, [pts], isClosed=True, color=color, thickness=2)
                            cv2.putText(orig_frame, zn.replace("_", " ").upper(),
                                        (int(zd['x_min']) + 4, int(zd['y_min']) + 18),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)

                        # ── Part 1: add streak info to screenshot ──
                        label_text = f"VIOLATION CONFIRMED streak={current_streak}"
                        cv2.putText(orig_frame,
                label_text,
                (10, orig_frame.shape[0] - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2)

                        cv2.imwrite(screenshot_path, orig_frame)

                        incident = {
                            "id":              incident_id,
                            "timestamp":       datetime.now().isoformat(),
                            "frame":           frame_idx,
                            "camera":          video,
                            "person_id":       person_id,
                            "violation":       violation_type,
                            "missing_gear":    missing_gear,
                            "zone":            zone_name,
                            "rule_index":      rule_idx,
                            "bbox":            [float(x1), float(y1), float(x2), float(y2)],
                            "screenshot_path": screenshot_path,
                            "rule_type":       rule_type,
                            "alert_message":   config['alert']['message'],
                            "streak_frames":   current_streak,
                            "rule_db_id":      rule.get("rule_db_id"),
                            "detected_objects": build_detected_objects(result),
                        }

                        append_incident(incident)

                        print(f"Frame {frame_idx}: person #{person_id} | rule[{rule_idx}] {rule_type} in {zone_name}"
                              + (f" | missing: {missing_gear}" if missing_gear else "")
                              + f" | streak={current_streak} → {incident_id} [FIRED]")

                        active_violations[cooldown_key] = frame_idx

                else:
                    # ── Part 1: reset streak if violation stops ──
                    if cooldown_key in streak_counters:
                        del streak_counters[cooldown_key]
                    # cleanup stale cooldown — ── Task 3: uses ALERT_COOLDOWN_FRAMES from Settings ──
                    if cooldown_key in active_violations:
                        if frame_idx - active_violations[cooldown_key] > ALERT_COOLDOWN_FRAMES:
                            del active_violations[cooldown_key]

except Exception as e:
    print(f"\n{'='*60}")
    print(f"[ERROR] Pipeline processing crashed: {e}")
    print(f"[ERROR] camera_id={camera_id}, source={video}")
    print(f"{'='*60}\n")

finally:
    if is_live_source:
        print(f"\n{'='*60}")
        print(f"[WARN] RTSP stream loop ended (camera_id={camera_id}, source={video})")
        print(f"[WARN] For a live camera this is unexpected — likely the stream dropped mid-pipeline.")
        print(f"[WARN] Auto-restart of the pipeline process is not yet implemented (see rtsp_design.md section 4).")
        print(f"{'='*60}\n")

# ============================================================
# DONE
# ============================================================
try:
    db = SessionLocal()
    final_count = db.query(Incident).filter(Incident.site_id == site_id).count()
    db.close()
    print(f"\n{'='*60}")
    print(f"Done. {final_count} total incidents in PostgreSQL.")
    print(f"{'='*60}\n")
except Exception:
    final_count = len(json.loads(INCIDENTS_FILE.read_text())) if INCIDENTS_FILE.exists() else 0
    print(f"\n{'='*60}")
    print(f"Done. {final_count} unique incidents saved to JSON fallback.")
    print(f"{'='*60}\n")