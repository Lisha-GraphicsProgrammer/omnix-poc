"""
OMNIX API smoke test — hits every endpoint and reports pass/fail.
Run: python test_api.py
"""
import requests
import json
import sys

BASE = "http://localhost:8000"
results = []

def test(name, method, path, expected_status=200, body=None, check=None):
    """Run one test. `check` is an optional lambda(response_json) -> bool."""
    url = f"{BASE}{path}"
    try:
        if method == "GET":
            r = requests.get(url, timeout=10)
        elif method == "POST":
            r = requests.post(url, json=body, timeout=130)
        elif method == "PUT":
            r = requests.put(url, json=body, timeout=10)
        else:
            raise ValueError(f"Unknown method: {method}")

        status_ok = r.status_code == expected_status
        check_ok = True
        check_msg = ""

        if status_ok and check:
            try:
                check_ok = check(r.json() if r.headers.get("content-type", "").startswith("application/json") else r.content)
            except Exception as e:
                check_ok = False
                check_msg = f" (check error: {e})"

        if status_ok and check_ok:
            results.append((True, name, f"{r.status_code}"))
            print(f"  ✅ {name:<40} [{r.status_code}]")
        else:
            results.append((False, name, f"got {r.status_code}, expected {expected_status}{check_msg}"))
            print(f"  ❌ {name:<40} [{r.status_code}] {check_msg}")
            if not status_ok:
                print(f"      Response: {r.text[:200]}")
    except requests.exceptions.ConnectionError:
        results.append((False, name, "Cannot connect"))
        print(f"  ❌ {name:<40} [CONNECTION REFUSED]")
    except Exception as e:
        results.append((False, name, str(e)))
        print(f"  ❌ {name:<40} [ERROR: {e}]")


print("=" * 60)
print("OMNIX API SMOKE TEST")
print("=" * 60)

print("\n[CORE]")
test("Root status",         "GET", "/",
     check=lambda j: "OMNIX" in j.get("status", ""))
test("List incidents",      "GET", "/api/incidents",
     check=lambda j: isinstance(j, list))
test("Pipeline config",     "GET", "/api/pipeline",
     check=lambda j: "rules" in j)
test("Stats",               "GET", "/api/stats",
     check=lambda j: "total" in j and "unique_persons" in j)

print("\n[CAMERAS & VIDEO]")
test("List cameras",        "GET", "/api/cameras",
     check=lambda j: isinstance(j, list) and len(j) == 8 and j[0]["id"] == 1)
test("Camera 1 is online",  "GET", "/api/cameras",
     check=lambda j: j[0]["status"] == "online" and j[0]["stream_url"] is not None)
test("Video snapshot",      "GET", "/api/video/snapshot",
     check=lambda b: isinstance(b, bytes) and len(b) > 1000)

print("\n[SETTINGS]")
test("Get settings",        "GET", "/api/settings",
     check=lambda j: all(k in j for k in ["detection", "alerts", "ai_model", "platform"]))
test("Update settings",     "PUT", "/api/settings",
     body={"detection": {"alert_cooldown_frames": 200}},
     check=lambda j: j["settings"]["detection"]["alert_cooldown_frames"] == 200)
# Restore default
requests.put(f"{BASE}/api/settings", json={"detection": {"alert_cooldown_frames": 150}})

print("\n[LLM RULE GENERATION] (slow - 30-60s)")
test("Generate rule from English", "POST", "/api/rules/generate",
     body={"instruction": "alert when person enters loading zone"},
     check=lambda j: "config" in j and "rules" in j["config"])

print("\n[DANGER ZONE] (destructive - skipped by default)")
print("  ⏭️  Flush alerts        SKIPPED (would delete incidents.json)")
print("  ⏭️  Reset tracks         SKIPPED (would reset ByteTrack)")

# Summary
print("\n" + "=" * 60)
passed = sum(1 for r in results if r[0])
total = len(results)
print(f"RESULT: {passed}/{total} passed")
print("=" * 60)

if passed < total:
    print("\nFAILURES:")
    for ok, name, msg in results:
        if not ok:
            print(f"  • {name}: {msg}")
    sys.exit(1)
else:
    print("✅ All APIs working")
    sys.exit(0)