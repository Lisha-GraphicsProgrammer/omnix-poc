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

print(f"\n{'='*60}")
print(f"Pipeline: {config['pipeline_id']}")
print(f"Description: {config['description']}")
print(f"Zones: {len(config.get('zones', []))}")
print(f"Rules: {len(config.get('rules', []))}")
print(f"Persistence frames: {PERSISTENCE_FRAMES}")
print(f"Alert cooldown frames: {ALERT_COOLDOWN_FRAMES}")
print(f"Global detection confidence: {GLOBAL_DETECTION_CONFIDENCE}")
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

def append_incident(incident: dict):
    if rule_id and site_id:
        try:
            db = SessionLocal()
            db_incident = Incident(
                rule_id=rule_id,
                camera_id=camera_id,
                site_id=site_id,
                timestamp=datetime.fromisoformat(incident["timestamp"]),
                frame_number=incident.get("frame"),
                person_track_id=incident.get("person_id"),
                violation_type=incident.get("violation"),
                detected_objects=None,
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
    print(f"  - {r['type']} in {r['zone']} (required: {r.get('required', [])})")
print()

# ============================================================
# PIPELINE STATE
# ============================================================
Path('incidents').mkdir(exist_ok=True)
if INCIDENTS_FILE.exists():
    INCIDENTS_FILE.unlink()

incident_count = 0

# ── Part 1: Cooldown tracker (existing) ──
active_violations = {}

# ── Part 1: Streak counter — tracks consecutive violation frames per (person_id, rule_idx) ──
# streak_counters[key] = number of consecutive frames with violation
streak_counters = {}

video = camera_source if camera_source else 'test_video.mp4'
print(f"Processing {video} (camera_id={camera_id})...")

# ── RTSP Phase 2: know whether this is a live stream (rtsp://) vs a finite file ──
is_live_source = isinstance(video, str) and video.startswith("rtsp://")

_cap = cv2.VideoCapture(video)
ORIG_W = int(_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
ORIG_H = int(_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
_cap.release()
print(f"[INFO] Original video resolution: {ORIG_W}x{ORIG_H}\n")

# Scale user-drawn zone polygons from snapshot space (854x480) to native res
SNAP_W, SNAP_H = 854, 480
for zn, zd in zones_map.items():
    if zd['source'] == 'user_drawn' and ORIG_W and ORIG_H:
        sx, sy = ORIG_W / SNAP_W, ORIG_H / SNAP_H
        zd['poly'] = [[p[0] * sx, p[1] * sy] for p in zd['coords']]
        zd['x_min'] = min(p[0] for p in zd['poly'])
        zd['x_max'] = max(p[0] for p in zd['poly'])
        zd['y_min'] = min(p[1] for p in zd['poly'])
        zd['y_max'] = max(p[1] for p in zd['poly'])
        print(f"[ZONE] '{zn}' user-drawn polygon scaled to native res ({len(zd['poly'])} points)")
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

                elif rule_type == "count_exceeded":
                    violation_occurred = True
                    violation_type = "person_in_zone"

                if violation_occurred:
                    # ── Part 1: increment streak counter ──
                    streak_counters[cooldown_key] = streak_counters.get(cooldown_key, 0) + 1
                    current_streak = streak_counters[cooldown_key]

                    # ── Part 1: only fire when streak reaches PERSISTENCE_FRAMES ──
                    # AND not in cooldown
                    if current_streak >= PERSISTENCE_FRAMES and cooldown_key not in active_violations:
                        incident_count += 1
                        incident_id     = f"inc_{incident_count:04d}"
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
                (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2)

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
