import json
from ultralytics import YOLO

CLASS_MAP = {
    "person": 0,
    "bicycle": 1,
    "car": 2,
    "truck": 7,
    "helmet": None,
    "vest": None
}

model = YOLO('yolov8n.pt')

with open('site_instructions.json') as f:
    configs = json.load(f)

for config in configs:
    print("\n" + "="*60)
    print(f"Testing: {config['alert_id']}")
    print(f"Description: {config['description']}")

    required = config['detection']['required_classes']
    print(f"Classes LLM wants: {required}")

    class_ids = []
    missing = []
    for cls in required:
        if cls in CLASS_MAP and CLASS_MAP[cls] is not None:
            class_ids.append(CLASS_MAP[cls])
            print(f"  OK: '{cls}' = YOLO class ID {CLASS_MAP[cls]}")
        else:
            missing.append(cls)
            print(f"  WARNING: '{cls}' NOT in standard YOLO")

    if not class_ids:
        print("RESULT: Cannot run — no valid YOLO classes")
        continue

    print(f"\nRunning YOLO on construction site video...")

    results = model(
        source='site_video.mp4',
        classes=class_ids,
        conf=0.5,
        save=True,
        show=False,
        stream=True
    )

    counts = {}
    max_per_frame = 0
    for r in results:
        if r.boxes:
            frame_count = len(r.boxes)
            if frame_count > max_per_frame:
                max_per_frame = frame_count
            for box in r.boxes:
                name = model.names[int(box.cls[0])]
                counts[name] = counts.get(name, 0) + 1

    print(f"Total detections: {counts}")
    print(f"Max detected in single frame: {max_per_frame}")
    print(f"Rule from LLM: {config['detection']['logic']['rule']}")
    print(f"Missing classes: {missing}")

    if missing:
        print(f"RESULT: PARTIAL — {missing} need custom model")
    else:
        print(f"RESULT: WORKS")

print("\n" + "="*60)
print("SITE VIDEO TEST COMPLETE")