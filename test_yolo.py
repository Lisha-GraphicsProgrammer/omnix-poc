from ultralytics import YOLO

model = YOLO('yolov8n.pt')

results = model(
    source='mega_cctv.mp4',
    classes=[0, 2, 3, 7],
    conf=0.5,
    save=True,
    show=True,
    stream=True
)

for r in results:
    pass

print("Detection complete!")
print("Output saved in runs/detect/predict/")