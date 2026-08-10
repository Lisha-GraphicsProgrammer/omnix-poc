"""
Self-Learning Pipeline — Step 7: Evaluation Agent

Runs the trained model against the held-out TEST split (never touched during
training or validation) and checks results against acceptance gates before
letting a candidate anywhere near human approval. A model that fails these
gates is rejected automatically — this is the "not every training run
produces a better model" safety check from the original design spec.
"""
import json
from pathlib import Path
from datetime import datetime, timezone
from ultralytics import YOLO

DATASETS_DIR = Path("datasets")

# v1 acceptance gates — deliberately modest since a 3-10 epoch toy run is
# what we're actually testing against; a real production run (50-100 epochs)
# would be expected to clear much higher bars. Tune per class/site later.
ACCEPTANCE_GATES = {
    "min_precision": 0.5,
    "min_recall": 0.4,
    "min_map50": 0.4,
}


def evaluate_model(class_name: str, weights_path: str) -> dict:
    """
    Evaluates weights_path against datasets/<class_name>/test split.
    Returns metrics + a pass/fail verdict against ACCEPTANCE_GATES.
    """
    if not Path(weights_path).exists():
        return {"success": False, "error": f"Weights not found at {weights_path}"}

    data_yaml = DATASETS_DIR / class_name / "data.yaml"
    if not data_yaml.exists():
        return {"success": False, "error": f"data.yaml not found at {data_yaml}"}

    try:
        model = YOLO(weights_path)
        # split="test" explicitly evaluates the held-out test set, not val
        results = model.val(data=str(data_yaml), split="test", verbose=False)

        precision = float(results.box.p.mean()) if len(results.box.p) else 0.0
        recall = float(results.box.r.mean()) if len(results.box.r) else 0.0
        map50 = float(results.box.map50)
        map50_95 = float(results.box.map)

        metrics = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "map50": round(map50, 4),
            "map50_95": round(map50_95, 4),
        }

        gate_failures = []
        if precision < ACCEPTANCE_GATES["min_precision"]:
            gate_failures.append(f"precision {precision:.3f} < required {ACCEPTANCE_GATES['min_precision']}")
        if recall < ACCEPTANCE_GATES["min_recall"]:
            gate_failures.append(f"recall {recall:.3f} < required {ACCEPTANCE_GATES['min_recall']}")
        if map50 < ACCEPTANCE_GATES["min_map50"]:
            gate_failures.append(f"mAP50 {map50:.3f} < required {ACCEPTANCE_GATES['min_map50']}")

        passed = len(gate_failures) == 0
        return {
            "success": True,
            "metrics": metrics,
            "gates": ACCEPTANCE_GATES,
            "passed": passed,
            "gate_failures": gate_failures,
        }
    except Exception as e:
        return {"success": False, "error": f"Evaluation failed: {e}"}


def run_for_job(job_id: int, db_session, TrainingJob):
    """Runs evaluation for a job and updates its DB row with metrics + verdict."""
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

    _push_stage("evaluating", "running", "Testing candidate model against held-out test set...")
    result = evaluate_model(job.class_name, job.model_path)

    if not result["success"]:
        job.status = "failed"
        job.error = result["error"]
        _push_stage("evaluating", "failed", result["error"])
        return

    job.metrics = result["metrics"]
    m = result["metrics"]
    detail = f"Precision {m['precision']:.2f}, Recall {m['recall']:.2f}, mAP50 {m['map50']:.2f}"

    if result["passed"]:
        job.current_stage = "awaiting_approval"
        _push_stage("evaluating", "done", detail + " — passed acceptance gates")
    else:
        job.status = "failed"
        job.error = "Failed acceptance gates: " + "; ".join(result["gate_failures"])
        _push_stage("evaluating", "failed", detail + " — " + "; ".join(result["gate_failures"]))


if __name__ == "__main__":
    import sys
    cls = sys.argv[1] if len(sys.argv) > 1 else "trousers"
    weights = sys.argv[2] if len(sys.argv) > 2 else f"runs/self_learning/{cls}_model/weights/best.pt"
    result = evaluate_model(cls, weights)
    print(json.dumps(result, indent=2))