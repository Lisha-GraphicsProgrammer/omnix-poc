from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import json
import os
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="OMNIX POC API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure incidents folder exists (prevents crash on fresh checkout)
os.makedirs("incidents", exist_ok=True)

app.mount("/screenshots", StaticFiles(directory="incidents"), name="screenshots")

# Ollama config (read from .env, defaults to lightweight model)
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")

# ============================================================
# EXISTING ENDPOINTS (unchanged)
# ============================================================

@app.get("/")
def root():
    return {"status": "OMNIX POC API running", "llm_provider": "ollama", "model": OLLAMA_MODEL}

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
        return {"total": 0, "unique_persons": 0, "zones_affected": []}
    with open(incidents_file, "r") as f:
        incidents = json.load(f)
    return {
        "total": len(incidents),
        "unique_persons": len(set(i["person_id"] for i in incidents)),
        "zones_affected": list(set(i["zone"] for i in incidents))
    }

# ============================================================
# NEW ENDPOINTS - LLM Rule Generation (Ollama)
# ============================================================

SYSTEM_PROMPT = """You are OMNIX's rule generator. Convert plain English safety instructions into valid pipeline_config.json for a YOLOv8 + ByteTrack computer vision pipeline.

AVAILABLE MODELS:
- "helmet" - detects construction hardhats
- "vest" - detects safety vests
- "person" - base YOLO person detection

AVAILABLE RULE TYPES:
- "person_in_zone" - alert when any person enters zone
- "missing_in_zone" - alert when person without required gear enters
- "count_exceeded" - alert when more than N people in zone

OUTPUT FORMAT (must match exactly):
{
  "pipeline_id": "auto_<short_descriptive_name>",
  "description": "<one line description>",
  "models": {
    "helmet": "runs/detect/helmet_model/weights/best.pt",
    "vest": "runs/detect/vest_model/weights/best.pt"
  },
  "zones": [
    {
      "name": "<zone_name>",
      "coords": [[100, 200], [500, 200], [500, 600], [100, 600]]
    }
  ],
  "rules": [
    {
      "type": "<rule_type>",
      "zone": "<zone_name>",
      "required": ["<gear>"],
      "primary": "person"
    }
  ],
  "alert": {
    "severity": "high",
    "message": "<alert message>"
  },
  "cooldown_seconds": 30
}

EXAMPLES:

User: Alert when person enters loading zone
Output:
{"pipeline_id": "auto_person_loading", "description": "Person detected in loading zone", "models": {}, "zones": [{"name": "loading_zone", "coords": [[100,200],[500,200],[500,600],[100,600]]}], "rules": [{"type": "person_in_zone", "zone": "loading_zone", "required": [], "primary": "person"}], "alert": {"severity": "high", "message": "Person in loading zone"}, "cooldown_seconds": 30}

User: Alert when worker without helmet enters loading zone
Output:
{"pipeline_id": "auto_helmet_loading", "description": "Worker without helmet in loading zone", "models": {"helmet": "runs/detect/helmet_model/weights/best.pt"}, "zones": [{"name": "loading_zone", "coords": [[100,200],[500,200],[500,600],[100,600]]}], "rules": [{"type": "missing_in_zone", "zone": "loading_zone", "required": ["helmet"], "primary": "person"}], "alert": {"severity": "high", "message": "Helmet required in loading zone"}, "cooldown_seconds": 30}

Only include models in "models" that are actually needed by the rule.
Output ONLY the JSON. No markdown code fences, no explanation, no preamble."""


@app.post("/api/rules/generate")
async def generate_rule(request: Request):
    """Convert English instruction to pipeline_config JSON via Ollama."""
    try:
        body = await request.json()
        instruction = body.get("instruction", "").strip()
        
        if not instruction:
            raise HTTPException(status_code=400, detail="instruction is required")
        
        # Build prompt for Ollama (combines system + user message)
        full_prompt = f"{SYSTEM_PROMPT}\n\nUser instruction: {instruction}\n\nJSON output:"
        
        # Call Ollama
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": full_prompt,
                "stream": False,
                "format": "json",
                "options": {
                    "temperature": 0.1,
                    "num_predict": 1024
                }
            },
            timeout=120
        )
        
        if response.status_code != 200:
            raise HTTPException(
                status_code=500,
                detail=f"Ollama error: {response.text}"
            )
        
        result = response.json()
        response_text = result.get("response", "").strip()
        
        # Strip markdown if present (defensive)
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
            response_text = response_text.strip()
        
        config = json.loads(response_text)
        
        return {
            "config": config,
            "instruction": instruction,
            "model_used": OLLAMA_MODEL,
            "provider": "ollama_local"
        }
        
    except requests.exceptions.ConnectionError:
        raise HTTPException(
            status_code=503,
            detail="Ollama is not running. Start it with: ollama serve"
        )
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=500,
            detail=f"LLM returned invalid JSON: {str(e)}. Raw: {response_text[:500]}"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/rules/apply")
async def apply_rule(request: Request):
    """Overwrite pipeline_config.json with new rule."""
    try:
        body = await request.json()
        config = body.get("config")
        
        if not config:
            raise HTTPException(status_code=400, detail="config is required")
        
        # Backup existing config
        existing = Path("pipeline_config.json")
        if existing.exists():
            backup_path = Path("pipeline_config.backup.json")
            with open(existing, "r") as src, open(backup_path, "w") as dst:
                dst.write(src.read())
        
        # Write new config
        with open("pipeline_config.json", "w") as f:
            json.dump(config, f, indent=2)
        
        return {
            "status": "applied",
            "message": "Rule applied. Restart pipeline to take effect.",
            "config_path": "pipeline_config.json"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))