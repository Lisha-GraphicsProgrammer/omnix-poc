"""
Self-Learning Pipeline — Step 4: Data Acquisition

Given a class name (e.g. "trousers"), performs a REAL live search against
Roboflow's Universe Search API (GET /universe/search) to find candidate
public datasets, ranks them, and downloads the best match. No hardcoded
class list — any class name the user asks for gets searched for real.
"""
import os
import json
import requests
from pathlib import Path
from dotenv import load_dotenv
from roboflow import Roboflow

load_dotenv()

DATASETS_DIR = Path("datasets")
UNIVERSE_SEARCH_URL = "https://api.roboflow.com/universe/search"


def search_universe(class_name: str, min_images: int = 50) -> list[dict]:
    """
    Live search against Roboflow Universe for datasets matching class_name.
    Returns a ranked list of candidates (best first), or [] if none found.
    """
    api_key = os.getenv("ROBOFLOW_API_KEY")
    if not api_key:
        return []

    query = f'class:{class_name} model:yolov8 images>{min_images}'
    try:
        resp = requests.get(
            UNIVERSE_SEARCH_URL,
            params={"q": query, "api_key": api_key, "page": 0},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[SELF-LEARNING] Universe search failed for '{class_name}': {e}")
        return []

    results = data.get("results", [])
    candidates = []
    for r in results:
        workspace_slug = (r.get("workspace") or {}).get("url")
        # Project slug is the last path segment of the dataset URL, e.g.
        # ".../collegeprojects/fashion-8y2pv" -> "fashion-8y2pv"
        dataset_url = r.get("url", "")
        project_slug = dataset_url.rstrip("/").split("/")[-1] if dataset_url else None
        if not workspace_slug or not project_slug:
            continue
        candidates.append({
            "workspace": workspace_slug,
            "project": project_slug,
            "version": r.get("latestVersion", 1),
            "images": r.get("images", 0),
            "stars": r.get("stars", 0),
            "license": r.get("license", "unknown"),
            "url": dataset_url,
        })

    # Prefer datasets in a practical size range for fast iteration (a few
    # hundred to a few thousand images) over raw maximum size. A 900-image
    # curated set trains and verifies in minutes; a 100k-image general
    # dataset (e.g. full COCO) can take an hour just to verify on CPU,
    # which defeats the purpose of a fast self-learning proof-of-concept.
    # Closest-to-3000 wins ties broken by stars (community trust signal).
    def rank_score(c):
        images = c["images"]
        size_score = -abs(images - 3000)
        return (size_score, c["stars"])

    candidates.sort(key=rank_score, reverse=True)
    return candidates


def acquire_dataset(class_name: str) -> dict:
    """
    Searches Universe live for class_name, downloads the top-ranked candidate.
    Returns a dict describing the outcome — always, even on failure.
    """
    api_key = os.getenv("ROBOFLOW_API_KEY")
    if not api_key:
        return {"success": False, "error": "ROBOFLOW_API_KEY not set in .env"}

    candidates = search_universe(class_name)
    if not candidates:
        return {
            "success": False,
            "error": f"No public Roboflow dataset found for class '{class_name}' "
                     f"(searched live via Universe Search API, 0 results with images>50).",
        }

    last_error = None
    for candidate in candidates[:3]:  # try top 3 in case one fails to download
        ws, proj, ver = candidate["workspace"], candidate["project"], candidate["version"]
        if not ws or not proj:
            continue
        try:
            rf = Roboflow(api_key=api_key)
            project = rf.workspace(ws).project(proj)
            project.version(ver).download("yolov8", location=str(DATASETS_DIR / class_name))
            img_dir = DATASETS_DIR / class_name / "train" / "images"
            image_count = sum(1 for _ in img_dir.glob("*")) if img_dir.exists() else 0
            if image_count == 0:
                last_error = f"{ws}/{proj} downloaded but produced 0 images (likely a partial/failed download)"
                continue
            return {
                "success": True,
                "path": str(DATASETS_DIR / class_name),
                "source": f"{ws}/{proj} v{ver}",
                "image_count": image_count,
                "license": candidate.get("license"),
                "candidates_considered": len(candidates),
            }
        except Exception as e:
            last_error = str(e)
            continue

    return {
        "success": False,
        "error": f"Found {len(candidates)} candidate dataset(s) for '{class_name}' but all failed to download. Last error: {last_error}",
    }


def run_for_job(job_id: int, db_session, TrainingJob):
    """Runs acquisition for a training job and updates its DB row with progress."""
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

    _push_stage("searching_data", "running", f"Searching Roboflow Universe for '{job.class_name}'...")
    result = acquire_dataset(job.class_name)

    if result["success"]:
        job.dataset_info = result
        job.current_stage = "preparing_dataset"
        _push_stage("searching_data", "done", f"Found {result['image_count']} images from {result['source']}")
    else:
        job.status = "failed"
        job.error = result["error"]
        _push_stage("searching_data", "failed", result["error"])


if __name__ == "__main__":
    import sys
    cls = sys.argv[1] if len(sys.argv) > 1 else "trousers"
    print(f"Searching live for: {cls}")
    candidates = search_universe(cls)
    print(f"Found {len(candidates)} candidates:")
    for c in candidates[:5]:
        print(f"  - {c['workspace']}/{c['project']} v{c['version']} · {c['images']} images · {c['stars']} stars")
    print()
    result = acquire_dataset(cls)
    print(json.dumps(result, indent=2))