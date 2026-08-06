"""
Self-Learning Pipeline — Step 5: Dataset Preparation

Verifies a downloaded dataset is clean and training-ready:
- every image actually opens (catches corrupted downloads)
- every label file is valid YOLO format (class_id x y w h, values in [0,1])
- reports class balance (how many labeled instances exist)
- confirms train/valid/test split is present and non-empty

Does NOT re-split data — Roboflow's own train/valid/test split is trusted
as-is for v1. This step is a quality gate before spending time training on
possibly-broken data, not a dataset engineering pipeline (v2: dedup across
splits, custom split ratios, synthetic augmentation).
"""
import json
from pathlib import Path
from PIL import Image

DATASETS_DIR = Path("datasets")


def _check_split(split_dir: Path) -> dict:
    images_dir = split_dir / "images"
    labels_dir = split_dir / "labels"
    if not images_dir.exists():
        return {"exists": False}

    image_files = list(images_dir.glob("*"))
    corrupted = []
    label_instance_count = 0
    malformed_labels = []

    for img_path in image_files:
        try:
            with Image.open(img_path) as im:
                im.verify()
        except Exception:
            corrupted.append(img_path.name)
            continue

        label_path = labels_dir / (img_path.stem + ".txt")
        if not label_path.exists():
            continue
        for line_num, line in enumerate(label_path.read_text().splitlines(), 1):
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) != 5:
                malformed_labels.append(f"{label_path.name}:{line_num}")
                continue
            try:
                cls_id, x, y, w, h = int(parts[0]), *map(float, parts[1:])
                if not all(0 <= v <= 1 for v in (x, y, w, h)):
                    malformed_labels.append(f"{label_path.name}:{line_num} (out of range)")
                    continue
            except ValueError:
                malformed_labels.append(f"{label_path.name}:{line_num} (parse error)")
                continue
            label_instance_count += 1

    return {
        "exists": True,
        "total_images": len(image_files),
        "corrupted_images": corrupted,
        "clean_images": len(image_files) - len(corrupted),
        "label_instances": label_instance_count,
        "malformed_labels": malformed_labels,
    }


def prepare_dataset(class_name: str) -> dict:
    dataset_dir = DATASETS_DIR / class_name
    if not dataset_dir.exists():
        return {"success": False, "error": f"No dataset found at {dataset_dir} — run acquisition first"}

    data_yaml = dataset_dir / "data.yaml"
    if not data_yaml.exists():
        return {"success": False, "error": f"data.yaml missing from {dataset_dir}"}

    report = {"success": True, "dataset_path": str(dataset_dir), "splits": {}}
    total_corrupted = 0
    total_malformed = 0
    total_instances = 0

    for split in ("train", "valid", "test"):
        result = _check_split(dataset_dir / split)
        report["splits"][split] = result
        if result.get("exists"):
            total_corrupted += len(result["corrupted_images"])
            total_malformed += len(result["malformed_labels"])
            total_instances += result["label_instances"]

    report["total_label_instances"] = total_instances
    report["total_corrupted_images"] = total_corrupted
    report["total_malformed_labels"] = total_malformed
    report["ready_for_training"] = (
        report["splits"].get("train", {}).get("clean_images", 0) > 0
        and total_instances > 0
    )
    if not report["ready_for_training"]:
        report["success"] = False
        report["error"] = "No clean, labeled training images available after verification"

    return report


def run_for_job(job_id: int, db_session, TrainingJob):
    """Runs dataset prep for a training job and updates its DB row."""
    from datetime import datetime, timezone
    job = db_session.query(TrainingJob).filter(TrainingJob.id == job_id).first()
    if not job:
        return

    def _push_stage(name, status, detail=None):
        stages = list(job.stages or [])
        stages.append({
            "name": name, "status": status, "detail": detail,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        })
        job.stages = stages
        job.current_stage = name if status == "running" else job.current_stage
        db_session.commit()

    _push_stage("preparing_dataset", "running", "Verifying images and labels...")
    result = prepare_dataset(job.class_name)

    if result["success"]:
        existing_info = dict(job.dataset_info or {})
        existing_info["prep_report"] = result
        job.dataset_info = existing_info
        job.current_stage = "training"
        detail = (f"{result['total_label_instances']} labeled instances verified across "
                  f"train/valid/test — {result['total_corrupted_images']} corrupted, "
                  f"{result['total_malformed_labels']} malformed labels skipped")
        _push_stage("preparing_dataset", "done", detail)
    else:
        job.status = "failed"
        job.error = result.get("error", "Dataset preparation failed")
        _push_stage("preparing_dataset", "failed", result.get("error"))


if __name__ == "__main__":
    import sys
    cls = sys.argv[1] if len(sys.argv) > 1 else "trousers"
    result = prepare_dataset(cls)
    print(json.dumps(result, indent=2))