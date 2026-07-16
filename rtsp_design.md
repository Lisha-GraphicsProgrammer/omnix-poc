# RTSP Camera Support — Design Note

**Status:** Design only, no code yet. Scope: get ONE real RTSP camera working end to end; multi-camera comes later.

---

## 1. Current flow vs. proposed flow

**Today:**
- `cameras.source` exists in the DB (`Camera.source`, `Text`, required) and is already populated per camera row.
- `VideoStream` in `api_server.py` is a **single global instance** (`video_stream = VideoStream()`), opened once at startup from `VIDEO_SOURCE_DEFAULT` — an env var (`VIDEO_SOURCE`), not the DB. It has zero awareness of which camera it belongs to.
- Every camera-facing endpoint (`/api/video/stream`, `/api/video/snapshot`, `/api/cameras`) hardcodes `camera_id == 1` as the only "live" camera. Any other camera row just returns its static DB fields with no actual video.
- `run_pipeline.py` is worse: `video = 'test_video.mp4'` is a **literal string**, completely disconnected from the DB. The `camera_id` it stamps onto incidents comes from `db.query(CameraModel).first()` — whichever camera row happens to be first, unrelated to what footage is actually being processed. So today, an incident's `camera_id` is essentially decorative, not accurate.

**Proposed:**
- `VideoStream` becomes keyed by `camera_id` (a `dict[int, VideoStream]` instead of one singleton), so each camera can hold its own OpenCV capture.
- On startup (and whenever an admin adds/edits a camera), the backend reads that camera's `source` field from the DB and opens it — file path, webcam index, or `rtsp://` URL, same `_parse_source()` logic that already exists, just driven by DB data instead of `.env`.
- `run_pipeline.py` takes a `camera_id` (new CLI arg or config field), looks up that camera's `Camera.source` from the DB via `SessionLocal()`, and passes that real source into `base_model.track(source=...)` instead of the hardcoded string. The `camera_id` written onto each `Incident` becomes the actual camera that produced the frame, not an arbitrary first-row lookup.

---

## 2. Admin flow — adding/editing a camera's RTSP URL

Add `PUT /api/cameras/{id}`, admin-only (mirrors the existing `PUT /api/zones/{zone_id}` and `PUT /api/settings` patterns already in `api_server.py`).

**Fields:** `name`, `location`, `source` (the important one). Validate `source`:
- Must be non-empty
- If it starts with `rtsp://`, accept as-is (can't pre-validate reachability without attempting a connect)
- Otherwise, existing `Path(source).exists()` check applies (file path case)

**Behavior on save:**
- Update the DB row
- If this camera is the currently "active" one being streamed, tear down its existing `VideoStream` and re-open with the new source (reusing `VideoStream.start()`, which already releases the old `cap` first)
- Return the updated camera object, including a `status` reflecting whether the new source opened successfully (`online`/`offline`), not just "saved OK"

Also worth a `POST /api/cameras` for adding a brand-new camera row, since right now camera rows only get created implicitly inside `create_zone()` — a real admin flow needs an explicit create endpoint too.

---

## 3. Multi-camera reality check

**What breaks today if 2+ cameras have real sources:**
- Only one `VideoStream` exists — a second camera has nowhere to stream from
- Every video endpoint hardcodes `camera_id == 1` — a second camera's stream/snapshot routes would need the same special-casing duplicated, or a proper lookup
- Only one `pipeline_config.json` and one `_pipeline_process` — today's architecture assumes one running pipeline for the whole site, not one per camera. Two cameras with different rules would stomp on each other's config file.
- `run_pipeline.py`'s DB lookups (`db.query(CameraModel).first()`, `db.query(Rule)...first()`) grab arbitrary single rows — there's no concept of "which camera does this rule apply to" flowing through yet, even though `Zone.camera_id` already exists in the schema.

**Proposed V1 scope (per Hains' suggestion):** ONE real RTSP camera working end to end — not solving multi-camera concurrency yet. Concretely:
- Extend `VideoStream` to be keyed by `camera_id`, but only actually populate/use one entry for V1
- `run_pipeline.py` accepts a single `camera_id`, resolves its real `source`, and that camera_id flows correctly into every `Incident`
- Defer: multiple simultaneous live pipelines, one-process-per-camera, per-camera `pipeline_config.json` files, cross-camera zone conflicts

This keeps the pilot blocker solved (one real customer camera works) without committing to the harder multi-camera architecture before it's actually needed.

---

## 4. Failure handling — RTSP drops

**Today's `VideoStream.read()`** only handles the "video file ended" case — it seeks back to frame 0 and retries. That's correct behavior for looping a local test file, but **wrong for a dropped RTSP connection**: seeking to frame 0 on a live stream that has disconnected does nothing useful.

**Proposed:**
- Track consecutive failed reads. After N consecutive failures (e.g. 10), treat the stream as dead — don't keep silently retrying frame-0 seeks
- On dead-stream detection: mark that camera's DB `status` as `"offline"`, attempt a reconnect (`cv2.VideoCapture(source)` fresh) with a backoff (e.g. retry every 5s, up to some cap), and log clearly so it's visible in server logs
- The existing `generate_frames()` "NO SIGNAL" placeholder already covers the frontend gracefully — keep that behavior, just make sure it triggers correctly once we're actually detecting real disconnects instead of assuming file-loop behavior
- `run_pipeline.py`: `base_model.track(source=..., stream=True)` returns a generator — if the underlying RTSP source drops mid-stream, that generator will likely just stop yielding results. The pipeline needs to distinguish "stream legitimately ended" (fine for a test file) from "stream dropped unexpectedly" (needs reconnect logic), otherwise a live pilot camera going down would just silently end the whole pipeline process.

This section intentionally stops at "here's the behavior we need," not full implementation — reconnect backoff strategy and exact failure thresholds are better tuned once we see real RTSP drop patterns from an actual pilot camera.

---

## 5. Testing without a real CCTV camera

Two practical options, cheapest first:

**Phone RTSP app (fastest, zero setup):** Apps like *IP Webcam* (Android) or *RTSP Camera*/*EpocCam* (iOS) turn a phone into an `rtsp://<phone-ip>:<port>/...` stream on the local network. Point `cv2.VideoCapture()` at that URL directly — this is the closest thing to a real camera we can get without buying hardware, and it's genuinely useful for testing reconnect/drop behavior (walk out of Wi-Fi range, stream dies, walk back, see if it reconnects).

**Local video file streamed as RTSP (repeatable, scriptable):** Run a lightweight RTSP server locally (e.g. `mediamtx`, formerly `rtsp-simple-server`) and push `test_video.mp4` into it on a loop via `ffmpeg`:
```
ffmpeg -re -stream_loop -1 -i test_video.mp4 -c copy -f rtsp rtsp://localhost:8554/test
```
Then point the camera's `source` at `rtsp://localhost:8554/test`. This gives a fully reproducible RTSP source for automated testing, and can simulate drops by killing/restarting the `ffmpeg` process on demand.

Recommend starting with the phone app for a quick gut-check that the RTSP plumbing works at all, then setting up the `mediamtx` + `ffmpeg` loop for repeatable dev/test cycles once the basic path is confirmed.