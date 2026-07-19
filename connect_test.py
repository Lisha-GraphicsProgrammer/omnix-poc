import json
from ultralytics import YOLO

# YOLO class name to ID mapping (COCO dataset)
CLASS_MAP = {
    "person": 0,
    "bicycle": 1,
    "car": 2,
    "truck": 7,
    "helmet": None  # NOT in standard YOLO
}

def run_from_json(json_file, video_path):
    with open(json_file) as f:
        config = json.load(f)

    print("\n" + "="*50)
    print(f"Testing: {json_file}")
    print(f"Description: {config['alert']['description']}")

    # Get classes to detect
    required = config['alert']['detection']['required_classes']
    print(f"Classes LLM wants: {required}")

    # Convert to YOLO IDs
    class_ids = []
    missing = []
    for cls in required:
        if cls in CLASS_MAP and CLASS_MAP[cls] is not None:
            class_ids.append(CLASS_MAP[cls])
            print(f"  OK: '{cls}' = YOLO class ID {CLASS_MAP[cls]}")
        else:
            missing.append(cls)
            print(f"  WARNING: '{cls}' NOT in standard YOLO - needs custom model")

    if not class_ids:
        print("RESULT: Cannot run - no valid YOLO classes found")
        return

    print(f"\nRunning YOLO with class IDs: {class_ids}")

    model = YOLO('yolov8n.pt')
    results = model(
        source=video_path,
        classes=class_ids,
        conf=0.5,
        save=True,
        show=False
    )

    # Count detections
    counts = {}
    for r in results:
        if r.boxes:
            for box in r.boxes:
                name = model.names[int(box.cls[0])]
                counts[name] = counts.get(name, 0) + 1

    print(f"Total detections: {counts}")
    print(f"Missing classes needing custom model: {missing}")

    # Show the rule
    logic = config['alert']['detection']['logic']
    print(f"Rule from LLM: {logic['rule']}")
    print(f"RESULT: {'WORKS' if not missing else 'PARTIAL - missing ' + str(missing)}")

# Run all 3
run_from_json("instruction_1_helmet.json", "mega_cctv.mp4")
run_from_json("instruction_2_vehicle.json", "mega_cctv.mp4")
run_from_json("instruction_3_count.json", "mega_cctv.mp4")

print("\n" + "="*50)
print("ALL TESTS COMPLETE")