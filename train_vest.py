from ultralytics import YOLO

model = YOLO('yolov8n.pt')

results = model.train(
    data='vest_dataset/data.yaml',
    epochs=50,
    imgsz=640,
    batch=8,
    name='vest_model',
    patience=10
)

print("Training complete!")
print(f"Best model saved at: runs/detect/vest_model/weights/best.pt")