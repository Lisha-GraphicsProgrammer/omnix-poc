from ultralytics import YOLO

model = YOLO('runs/detect/helmet_model/weights/best.pt')

# Test on single frame
results = model('site_video.mp4', conf=0.25, save=False, stream=True)

for i, r in enumerate(results):
    if i > 50:  # check first 50 frames only
        break
    if r.boxes and len(r.boxes) > 0:
        for box in r.boxes:
            name = model.names[int(box.cls[0])]
            conf = float(box.conf[0])
            print(f"Frame {i}: {name} — confidence {conf:.2f}")