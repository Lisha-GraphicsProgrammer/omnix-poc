"""
Download datasets and train forklift, gloves, ladder models.
Run this script — it handles everything automatically.
"""
from roboflow import Roboflow
from ultralytics import YOLO
import os, shutil

API_KEY = "wwh6cbaO67SzQrWTWtzS"
rf = Roboflow(api_key=API_KEY)

def download_dataset(workspace, project, version, dst_dir):
    if os.path.exists(dst_dir) and os.path.exists(f"{dst_dir}/data.yaml"):
        print(f"  ✅ Already downloaded: {dst_dir}")
        return True
    try:
        proj = rf.workspace(workspace).project(project)
        ver = proj.version(version)
        ver.download("yolov8", location=dst_dir)
        print(f"  ✅ Downloaded to {dst_dir}")
        return True
    except Exception as e:
        print(f"  ❌ Failed: {e}")
        return False

def train_model(data_yaml, model_name, epochs=15):
    dst = f"runs/detect/{model_name}_model/weights/best.pt"
    # Check if already properly trained (> 3MB means real model not placeholder)
    if os.path.exists(dst) and os.path.getsize(dst) > 3 * 1024 * 1024:
        # Check if it's a placeholder (same size as yolov8n.pt = 6.2MB base)
        base_size = os.path.getsize("yolov8n.pt")
        current_size = os.path.getsize(dst)
        if abs(current_size - base_size) < 100000:
            print(f"  ⚠ {model_name} is a placeholder — training proper model...")
        else:
            print(f"  ✅ {model_name} already trained ({current_size/1024/1024:.1f} MB)")
            return True

    print(f"\n  Training {model_name} ({epochs} epochs)...")
    model = YOLO("yolov8n.pt")
    results = model.train(
        data=data_yaml,
        epochs=epochs,
        imgsz=640,
        project="runs/detect",
        name=f"{model_name}_model",
        exist_ok=True,
        patience=5,
        batch=8,
        workers=0,
        verbose=False,
    )
    trained = f"runs/detect/{model_name}_model/weights/best.pt"
    if os.path.exists(trained):
        mAP = results.results_dict.get('metrics/mAP50(B)', 0)
        print(f"  ✅ {model_name} trained! mAP@50: {mAP:.3f}")
        return True
    return False

# ─── 1. Forklift ──────────────────────────────────────────────────────────────
print("\n" + "="*50)
print("1. FORKLIFT MODEL")
print("="*50)
# Dataset already downloaded as Forklift-2
if os.path.exists("Forklift-2/data.yaml"):
    train_model("Forklift-2/data.yaml", "forklift", epochs=15)
else:
    print("  Downloading forklift dataset...")
    download_dataset("epp-internship-0rrmj", "forklift-gfijl", 2, "Forklift-2")
    train_model("Forklift-2/data.yaml", "forklift", epochs=15)

# ─── 2. Gloves ────────────────────────────────────────────────────────────────
print("\n" + "="*50)
print("2. GLOVES MODEL")
print("="*50)
print("  Downloading gloves dataset...")
if download_dataset("vlworkspace", "yolo-detection-helmet-gloves", 1, "gloves_dataset"):
    train_model("gloves_dataset/data.yaml", "gloves", epochs=15)
else:
    # Try alternative
    if download_dataset("experimental-m8syc", "gloves-annotated-dataset-wzwtz", 1, "gloves_dataset"):
        train_model("gloves_dataset/data.yaml", "gloves", epochs=15)

# ─── 3. Ladder ────────────────────────────────────────────────────────────────
print("\n" + "="*50)
print("3. LADDER MODEL")
print("="*50)
print("  Downloading ladder dataset...")
if download_dataset("roboflow-universe-projects", "ladder-tpqmd", 1, "ladder_dataset"):
    train_model("ladder_dataset/data.yaml", "ladder", epochs=15)
else:
    if download_dataset("constructions-hazards", "ladder-s1iup", 1, "ladder_dataset"):
        train_model("ladder_dataset/data.yaml", "ladder", epochs=15)

# ─── Summary ──────────────────────────────────────────────────────────────────
print("\n" + "="*50)
print("FINAL SUMMARY:")
base_size = os.path.getsize("yolov8n.pt")
for name in ["forklift", "fire", "smoke", "gloves", "ladder"]:
    dst = f"runs/detect/{name}_model/weights/best.pt"
    if os.path.exists(dst):
        size = os.path.getsize(dst)
        is_placeholder = abs(size - base_size) < 100000
        tag = "⚠ placeholder" if is_placeholder else "✅ trained"
        print(f"  {tag} {name}: {size/1024/1024:.1f} MB")
    else:
        print(f"  ❌ {name}: missing")
print("="*50)