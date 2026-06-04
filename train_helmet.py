from ultralytics import YOLO

# Load base YOLOv8 model
model = YOLO('yolov8n.pt')

# Train on helmet dataset
results = model.train(
    data='helmet_dataset/data.yaml',
    epochs=20,
    imgsz=640,
    batch=8,
    name='helmet_model',
    patience=5
)

print("Training complete!")
print("Model saved in runs/detect/helmet_model/")