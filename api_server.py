from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import json
from pathlib import Path

app = FastAPI(title="OMNIX POC API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/screenshots", StaticFiles(directory="incidents"), name="screenshots")

@app.get("/")
def root():
    return {"status": "OMNIX POC API running"}

@app.get("/api/incidents")
def get_incidents():
    incidents_file = Path("incidents.json")
    if not incidents_file.exists():
        return []
    with open(incidents_file, "r") as f:
        incidents = json.load(f)
    for inc in incidents:
        if "screenshot_path" in inc:
            filename = inc["screenshot_path"].replace("incidents/", "")
            inc["screenshot_url"] = f"http://localhost:8000/screenshots/{filename}"
    return incidents

@app.get("/api/pipeline")
def get_pipeline():
    with open("pipeline_config.json", "r") as f:
        return json.load(f)

@app.get("/api/stats")
def get_stats():
    incidents_file = Path("incidents.json")
    if not incidents_file.exists():
        return {"total": 0, "unique_persons": 0}
    with open(incidents_file, "r") as f:
        incidents = json.load(f)
    return {
        "total": len(incidents),
        "unique_persons": len(set(i["person_id"] for i in incidents)),
        "zones_affected": list(set(i["zone"] for i in incidents))
    }