"""
OMNIX Universal Test Suite — Run ALL models against ALL test videos.
Detects every recognizable object in every video, saves screenshots,
generates per-video and per-object stats.

Usage:
    python run_test_suite.py

Output:
    incidents.json     (every detection, tagged with source video + object class)
    incidents/         (annotated screenshots)
    test_summary.json  (per-video × per-object detection counts)
"""
import json
import cv2
from datetime import datetime
from pathlib import Path
from collections import defaultdict
from ultralytics import YOLO

# ============================================================
# VIDEOS TO TEST
# ============================================================
TEST_VIDEOS = [
    "mega_cctv.mp4",
    "gloves.mp4",
    "forklift_person_helmet_gloves.mp4",
    "fire_smoke.mp4",
    "smoke_fire.mp4",
    "ladder_helmet_person.mp4",
    "ladder_helmet_vest_gloves_person.mp4",
    "helmet_gloves_person_vest.mp4",
]

# Detect 1 frame every N — keeps screenshot count sane (~20-50 per video)
FRAME_SAMPLE_RATE = 30  # one frame per second at 30fps

# Per-object color for bounding boxes (BGR)
COLORS = {
    "person":   (255, 100, 0),     # orange
    "helmet":   (0, 200, 255),     # cyan
    "vest":     (0, 255, 100),     # green
    "forklift": (255, 0, 200),     # magenta
    "fire":     (0, 0, 255),       # pure bright red
    "smoke":    (160, 160, 160),   # dimmer grey so fire stands out
    "gloves":   (0, 255, 255),     # yellow
    "ladder":   (200, 100, 255),   # purple
    "truck":    (200, 200, 0),     # teal
}

# Draw priority — higher value = drawn later = appears on top of other boxes
DRAW_PRIORITY = {
    "fire":     100,
    "forklift":  50,
    "smoke":     40,
    "person":    30,
    "helmet":    20,
    "vest":      20,
    "truck":     15,
    "gloves":    10,
    "ladder":     5,
}

# ============================================================
# LOAD MODEL REGISTRY + ALL MODELS
# ============================================================
with open("model_registry.json", "r") as f:
    registry = json.load(f)

print("\n" + "=" * 70)
print("OMNIX UNIVERSAL TEST SUITE")
print("=" * 70)
print("\n[STEP 1] Loading all models from registry...")

loaded_models = {}
for name, entry in registry.items():
    weights_path = entry.get("weights") or entry.get("model", "yolov8n.pt")
    if not Path(weights_path).exists():
        print(f"  [SKIP] {name}: {weights_path} not found")
        continue
    try:
        loaded_models[name] = {
            "model":      YOLO(weights_path),
            "confidence": entry.get("confidence", 0.5),
            "type":       entry.get("type", "custom"),
            "class_id":   entry.get("class_id"),
        }
        print(f"  [OK]   {name:<10} from {weights_path}")
    except Exception as e:
        print(f"  [FAIL] {name}: {e}")

print(f"\n[INFO] {len(loaded_models)} models loaded: {list(loaded_models.keys())}\n")

# ============================================================
# CLEAR PREVIOUS RESULTS
# ============================================================
INCIDENTS_FILE = Path("incidents.json")
INCIDENTS_DIR  = Path("incidents")
INCIDENTS_DIR.mkdir(exist_ok=True)

if INCIDENTS_FILE.exists():
    INCIDENTS_FILE.unlink()
for f in INCIDENTS_DIR.glob("*.jpg"):
    f.unlink()
print("[INFO] Cleared previous incidents\n")

incident_count   = 0
all_incidents    = []
stats            = defaultdict(lambda: defaultdict(int))  # stats[video][object] = count

def save_incidents():
    tmp = INCIDENTS_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(all_incidents, f, indent=2)
    tmp.replace(INCIDENTS_FILE)

# ============================================================
# PROCESS A SINGLE VIDEO — run all models, capture all detections
# ============================================================
def process_video(video_path):
    global incident_count

    print("=" * 70)
    print(f"[VIDEO] {video_path}")
    print("=" * 70)

    if not Path(video_path).exists():
        print(f"  [SKIP] File not found\n")
        return

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"  [SKIP] Couldn't open video\n")
        return

    width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps    = cap.get(cv2.CAP_PROP_FPS) or 30
    total  = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"  Resolution: {width}x{height} | FPS: {fps:.1f} | Frames: {total}")

    frame_idx       = 0
    video_incidents = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # Sample frames — don't process every frame, too slow + redundant
        if frame_idx % FRAME_SAMPLE_RATE != 0:
            frame_idx += 1
            continue

        # Run every loaded model on this frame
        detections_this_frame = []  # [(obj_name, bbox, conf), ...]

        for obj_name, mdata in loaded_models.items():
            model = mdata["model"]
            conf  = mdata["confidence"]

            # COCO models filter by class_id, custom models predict all their classes
            if mdata["type"] == "coco_default" and mdata["class_id"] is not None:
                results = model(frame, conf=conf, classes=[mdata["class_id"]], verbose=False)
            else:
                results = model(frame, conf=conf, verbose=False)

            if results[0].boxes is None or len(results[0].boxes) == 0:
                continue

            boxes  = results[0].boxes.xyxy.cpu().numpy()
            confs  = results[0].boxes.conf.cpu().numpy()

            for box, c in zip(boxes, confs):
                detections_this_frame.append((obj_name, box, float(c)))

        if not detections_this_frame:
            frame_idx += 1
            continue

        # Annotate frame with ALL detections — draw priority objects last (on top)
        annotated        = frame.copy()
        detected_classes = set()

        detections_sorted = sorted(
            detections_this_frame,
            key=lambda d: DRAW_PRIORITY.get(d[0], 0),
        )

        for obj_name, box, c in detections_sorted:
            x1, y1, x2, y2 = map(int, box)
            color     = COLORS.get(obj_name, (200, 200, 200))
            thickness = 3 if obj_name in ("fire", "smoke") else 2

            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, thickness)
            label = f"{obj_name} {c:.2f}"
            (lw, lh), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)
            cv2.rectangle(annotated, (x1, y1 - lh - 8), (x1 + lw + 6, y1), color, -1)
            cv2.putText(annotated, label, (x1 + 3, y1 - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)
            detected_classes.add(obj_name)
            stats[video_path][obj_name] += 1

        # Add video label badge top-left
        label_text = f"{Path(video_path).stem}  |  frame {frame_idx}"
        cv2.rectangle(annotated, (0, 0), (360, 32), (40, 40, 40), -1)
        cv2.putText(annotated, label_text, (8, 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 200), 2)

        # Save screenshot
        incident_count  += 1
        video_incidents += 1
        incident_id      = f"inc_{incident_count:04d}"
        screenshot_path  = f"incidents/{incident_id}.jpg"
        cv2.imwrite(screenshot_path, annotated)

        all_incidents.append({
            "id":               incident_id,
            "timestamp":        datetime.now().isoformat(),
            "frame":            frame_idx,
            "camera":           video_path,
            "detected_objects": sorted(list(detected_classes)),
            "detection_count":  len(detections_this_frame),
            "screenshot_path":  screenshot_path,
            "alert_message":    f"{', '.join(sorted(detected_classes))} detected in {Path(video_path).stem}",
            "severity":         "high" if {"fire", "smoke"} & detected_classes else "medium",
            "zone":             "test_zone",
        })

        if video_incidents % 5 == 0:
            save_incidents()  # Periodic save in case of crash

        print(f"  Frame {frame_idx:>5}: detected {sorted(list(detected_classes))} → {incident_id}")

        frame_idx += 1

    cap.release()
    save_incidents()
    print(f"\n  [DONE] {video_path}: {video_incidents} screenshots saved\n")

# ============================================================
# RUN ALL VIDEOS
# ============================================================
print("[STEP 2] Processing videos...\n")

for video_path in TEST_VIDEOS:
    process_video(video_path)

# ============================================================
# FINAL REPORT
# ============================================================
print("=" * 70)
print("FINAL REPORT")
print("=" * 70)

all_objects = sorted(loaded_models.keys())
col_width = max(8, max(len(o) for o in all_objects) + 1)
header = f"{'Video':<32} " + " ".join(f"{o:<{col_width}}" for o in all_objects)
print(header)
print("-" * len(header))

for video in TEST_VIDEOS:
    video_short = Path(video).stem[:30]
    row_parts   = []
    for obj in all_objects:
        count = stats[video].get(obj, 0)
        row_parts.append(f"{count:<{col_width}}")
    print(f"{video_short:<32} " + " ".join(row_parts))

print("-" * len(header))
print(f"\nTotal screenshots saved: {incident_count}")
print(f"Incidents file:          {INCIDENTS_FILE}")
print(f"Screenshots directory:   {INCIDENTS_DIR}/")
print("=" * 70 + "\n")

# Save summary
with open("test_summary.json", "w") as f:
    json.dump({
        "ran_at":          datetime.now().isoformat(),
        "videos_tested":   TEST_VIDEOS,
        "models_loaded":   list(loaded_models.keys()),
        "per_video_stats": {v: dict(s) for v, s in stats.items()},
        "total_incidents": incident_count,
    }, f, indent=2)

print("[OK] test_summary.json written\n")