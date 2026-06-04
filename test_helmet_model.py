from ultralytics import YOLO

# Load YOUR trained helmet model
model = YOLO('runs/detect/helmet_model/weights/best.pt')

# Run on construction site video
results = model(
    source='site_video.mp4',
    conf=0.5,
    save=True,
    show=True
)

print("Done! Check runs/detect/predict folder for output video")