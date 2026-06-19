import requests
import os
import shutil

def download_file(url, dst_path, label):
    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    print(f"\nDownloading {label}...")
    try:
        r = requests.get(url, stream=True, timeout=120,
                        headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            print(f"  ❌ HTTP {r.status_code}")
            return False
        with open(dst_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        size = os.path.getsize(dst_path) / 1024 / 1024
        if size < 1.0:
            print(f"  ❌ File too small ({size:.2f} MB)")
            os.remove(dst_path)
            return False
        print(f"  ✅ Saved! ({size:.1f} MB)")
        return True
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return False

DOWNLOADS = [
    # Fire + Smoke — weights are in /weights/ subfolder
    (
        "https://github.com/luminous0219/fire-and-smoke-detection-yolov8/raw/main/weights/best.pt",
        "runs/detect/fire_model/weights/best.pt",
        "fire+smoke (luminous0219)"
    ),
]

for url, dst, label in DOWNLOADS:
    if os.path.exists(dst):
        size = os.path.getsize(dst) / 1024 / 1024
        print(f"\n✅ {label} already exists ({size:.1f} MB) — skipping")
        continue
    if download_file(url, dst, label):
        # Reuse same model for smoke
        smoke_dst = "runs/detect/smoke_model/weights/best.pt"
        os.makedirs(os.path.dirname(smoke_dst), exist_ok=True)
        shutil.copy(dst, smoke_dst)
        print(f"  ✅ Copied to smoke model too")

# Forklift, gloves, ladder already have yolov8n placeholder
for model_name in ["forklift", "gloves", "ladder"]:
    dst = f"runs/detect/{model_name}_model/weights/best.pt"
    if not os.path.exists(dst):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy("yolov8n.pt", dst)
        print(f"\n⚠ {model_name}: using yolov8n.pt placeholder")

print("\n" + "=" * 50)
print("Summary:")
for name in ["forklift", "fire", "smoke", "gloves", "ladder"]:
    dst = f"runs/detect/{name}_model/weights/best.pt"
    if os.path.exists(dst):
        size = os.path.getsize(dst) / 1024 / 1024
        print(f"  ✅ {name}: {size:.1f} MB")
    else:
        print(f"  ❌ {name}: missing")
print("=" * 50)