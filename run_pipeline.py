import json
import cv2
from datetime import datetime
from pathlib import Path
from ultralytics import YOLO

with open('pipeline_config.json', 'r') as f:
    config = json.load(f)

print(f"Pipeline: {config['pipeline_id']}")
print(f"Description: {config['description']}\n")

models = {}
for name, path in config['models'].items():
    if Path(path).exists():
        try:
            models[name] = YOLO(path)
            print(f"Loaded {name} model")
        except Exception as e:
            print(f"FAILED to load {name}: {e}")
    else:
        print(f"Skipped {name} (file not found at {path})")

base_model = YOLO('yolov8n.pt')
print("Loaded base YOLO for person detection\n")

Path('incidents').mkdir(exist_ok=True)
incidents = []
incident_count = 0
active_violations = {}

video = 'test_video.mp4'
print(f"Processing {video}...\n")

zone = config['zones'][0]['coords']
zone_x_min = min(p[0] for p in zone)
zone_x_max = max(p[0] for p in zone)
zone_y_min = min(p[1] for p in zone)
zone_y_max = max(p[1] for p in zone)

results = base_model.track(source=video, persist=True, classes=[0], stream=True, conf=0.5, verbose=False)

for frame_idx, result in enumerate(results):
    if result.boxes is None or result.boxes.id is None:
        continue

    for box, track_id in zip(result.boxes.xyxy.cpu().numpy(), result.boxes.id.cpu().numpy()):
        person_id = int(track_id)
        x1, y1, x2, y2 = box
        person_center_x = (x1 + x2) / 2
        person_bottom_y = y2

        in_zone = (zone_x_min <= person_center_x <= zone_x_max and 
                   zone_y_min <= person_bottom_y <= zone_y_max)

        if in_zone:
            if person_id not in active_violations:
                incident_count += 1
                incident_id = f"inc_{incident_count:04d}"
                screenshot_path = f"incidents/{incident_id}.jpg"
                cv2.imwrite(screenshot_path, result.orig_img)

                incident = {
                    "id": incident_id,
                    "timestamp": datetime.now().isoformat(),
                    "frame": frame_idx,
                    "camera": video,
                    "person_id": person_id,
                    "violation": "person_in_zone",
                    "zone": config['zones'][0]['name'],
                    "bbox": [float(x1), float(y1), float(x2), float(y2)],
                    "screenshot_path": screenshot_path
                }
                incidents.append(incident)
                print(f"Frame {frame_idx}: person #{person_id} entered zone → {incident_id}")

            active_violations[person_id] = frame_idx

        else:
            if person_id in active_violations:
                last_seen = active_violations[person_id]
                if frame_idx - last_seen > 150:
                    del active_violations[person_id]

with open('incidents.json', 'w') as f:
    json.dump(incidents, f, indent=2)

print(f"\nDone. {len(incidents)} unique incidents saved to incidents.json")
print(f"Screenshots saved to incidents/ folder")