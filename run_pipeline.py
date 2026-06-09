import json
import cv2
from datetime import datetime
from pathlib import Path
from ultralytics import YOLO

# ============================================================
# CONFIG LOADING
# ============================================================
with open('pipeline_config.json', 'r') as f:
    config = json.load(f)

print(f"\n{'='*60}")
print(f"Pipeline: {config['pipeline_id']}")
print(f"Description: {config['description']}")
print(f"{'='*60}\n")

# ============================================================
# MODEL LOADING
# ============================================================
models = {}
for name, path in config['models'].items():
    if Path(path).exists():
        try:
            models[name] = YOLO(path)
            print(f"[OK] Loaded {name} model")
        except Exception as e:
            print(f"[FAIL] Could not load {name}: {e}")
    else:
        print(f"[SKIP] {name} (file not found at {path})")

base_model = YOLO('yolov8n.pt')
print(f"[OK] Loaded base YOLO for person detection\n")

# ============================================================
# HELPER: Check if person has required gear
# ============================================================
def bbox_overlap(box1, box2):
    """Calculate IoU-like overlap between two bboxes (x1,y1,x2,y2)."""
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
    
    # Return ratio of gear bbox inside person bbox
    return intersection / box2_area


def check_required_gear(person_bbox, frame, required_gear, loaded_models):
    """
    Check if person has required gear (helmet, vest, etc).
    Returns list of MISSING gear items.
    """
    missing = []
    
    for gear_name in required_gear:
        if gear_name not in loaded_models:
            print(f"  [WARN] Required gear '{gear_name}' but model not loaded, skipping check")
            continue
        
        # Run gear detection on full frame
        gear_results = loaded_models[gear_name](frame, verbose=False, conf=0.4)
        
        # Check if any gear detection overlaps with this person
        has_gear = False
        if gear_results[0].boxes is not None and len(gear_results[0].boxes) > 0:
            for gear_box in gear_results[0].boxes.xyxy.cpu().numpy():
                overlap = bbox_overlap(person_bbox, gear_box)
                if overlap > 0.3:  # 30% of gear bbox inside person bbox
                    has_gear = True
                    break
        
        if not has_gear:
            missing.append(gear_name)
    
    return missing


# ============================================================
# PIPELINE STATE
# ============================================================
Path('incidents').mkdir(exist_ok=True)
incidents = []
incident_count = 0
active_violations = {}

video = 'test_video.mp4'
print(f"Processing {video}...")

# Get zone coords
zone = config['zones'][0]['coords']
zone_name = config['zones'][0]['name']
zone_x_min = min(p[0] for p in zone)
zone_x_max = max(p[0] for p in zone)
zone_y_min = min(p[1] for p in zone)
zone_y_max = max(p[1] for p in zone)

# Get rule
rule = config['rules'][0]
rule_type = rule['type']
required_gear = rule.get('required', [])

print(f"Rule type: {rule_type}")
print(f"Required gear: {required_gear if required_gear else 'none'}")
print(f"Zone: {zone_name}\n")

# ============================================================
# MAIN PROCESSING LOOP
# ============================================================
results = base_model.track(
    source=video, 
    persist=True, 
    classes=[0],  # person only
    stream=True, 
    conf=0.5, 
    verbose=False
)

for frame_idx, result in enumerate(results):
    if result.boxes is None or result.boxes.id is None:
        continue
    
    for box, track_id in zip(result.boxes.xyxy.cpu().numpy(), result.boxes.id.cpu().numpy()):
        person_id = int(track_id)
        x1, y1, x2, y2 = box
        person_center_x = (x1 + x2) / 2
        person_bottom_y = y2
        
        # Check if person is in zone
        in_zone = (
            zone_x_min <= person_center_x <= zone_x_max and 
            zone_y_min <= person_bottom_y <= zone_y_max
        )
        
        if not in_zone:
            # Check cooldown — person left zone
            if person_id in active_violations:
                last_seen = active_violations[person_id]
                if frame_idx - last_seen > 150:
                    del active_violations[person_id]
            continue
        
        # ========================================
        # PERSON IS IN ZONE — apply rule logic
        # ========================================
        violation_occurred = False
        violation_type = "person_in_zone"
        missing_gear = []
        
        if rule_type == "missing_in_zone" and required_gear:
            # Check if person has required gear
            missing_gear = check_required_gear(
                (x1, y1, x2, y2),
                result.orig_img,
                required_gear,
                models
            )
            
            if missing_gear:
                violation_occurred = True
                violation_type = f"missing_{'_'.join(missing_gear)}"
        
        elif rule_type == "person_in_zone":
            violation_occurred = True
            violation_type = "person_in_zone"
        
        elif rule_type == "count_exceeded":
            # Future: count persons in zone, fire if exceeds threshold
            # For now, treat as person_in_zone
            violation_occurred = True
            violation_type = "person_in_zone"
        
        # ========================================
        # FIRE ALERT (with cooldown dedup)
        # ========================================
        if violation_occurred and person_id not in active_violations:
            incident_count += 1
            incident_id = f"inc_{incident_count:04d}"
            screenshot_path = f"incidents/{incident_id}.jpg"
            
            # Save screenshot with detection overlays
            annotated = result.plot()
            cv2.imwrite(screenshot_path, annotated)
            
            incident = {
                "id": incident_id,
                "timestamp": datetime.now().isoformat(),
                "frame": frame_idx,
                "camera": video,
                "person_id": person_id,
                "violation": violation_type,
                "missing_gear": missing_gear,
                "zone": zone_name,
                "bbox": [float(x1), float(y1), float(x2), float(y2)],
                "screenshot_path": screenshot_path,
                "rule_type": rule_type,
                "alert_message": config['alert']['message']
            }
            incidents.append(incident)
            
            if missing_gear:
                print(f"Frame {frame_idx}: person #{person_id} missing {missing_gear} in {zone_name} → {incident_id}")
            else:
                print(f"Frame {frame_idx}: person #{person_id} in {zone_name} → {incident_id}")
        
        # Update cooldown timer
        active_violations[person_id] = frame_idx

# ============================================================
# SAVE RESULTS
# ============================================================
with open('incidents.json', 'w') as f:
    json.dump(incidents, f, indent=2)

print(f"\n{'='*60}")
print(f"Done. {len(incidents)} unique incidents saved.")
print(f"  incidents.json")
print(f"  incidents/ folder ({len(incidents)} screenshots)")
print(f"{'='*60}\n")