import cv2
from ultralytics import YOLO

person_model = YOLO('yolov8n.pt')
helmet_model = YOLO('runs/detect/helmet_model/weights/best.pt')

cap = cv2.VideoCapture('site_video.mp4')
width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
fps    = int(cap.get(cv2.CAP_PROP_FPS))

out = cv2.VideoWriter(
    'tracked_alert_output.mp4',
    cv2.VideoWriter_fourcc(*'mp4v'),
    fps, (width, height)
)

ZONE = (10, 10, 350, 470)
COOLDOWN_FRAMES = fps * 30  # 30 seconds cooldown

# Tracking dictionaries
active_violations = {}   # {person_id: first_alert_frame}
last_alert_frame  = {}   # {person_id: last_alert_frame}
violation_log     = []   # list of completed events

def is_in_zone(box, zone):
    x1, y1, x2, y2 = box
    cx = (x1 + x2) / 2
    cy = (y1 + y2) / 2
    zx1, zy1, zx2, zy2 = zone
    return zx1 < cx < zx2 and zy1 < cy < zy2

def is_helmet_near(person_box, helmet_boxes):
    px1, py1, px2, py2 = person_box
    head_y2 = py1 + (py2 - py1) * 0.5
    for hx1, hy1, hx2, hy2 in helmet_boxes:
        hcx = (hx1 + hx2) / 2
        hcy = (hy1 + hy2) / 2
        if px1 < hcx < px2 and py1 < hcy < head_y2:
            return True
    return False

frame_count   = 0
unique_events = 0

print("Processing with ByteTrack deduplication...")

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        break

    frame_count += 1

    # Track persons with ByteTrack — gives persistent IDs
    track_results = person_model.track(
        frame,
        classes=[0],
        conf=0.3,
        persist=True,
        tracker='bytetrack.yaml',
        verbose=False
    )

    # Detect helmets
    helmet_results = helmet_model(frame, conf=0.3, verbose=False)

    # Collect helmet boxes
    helmet_boxes = []
    if helmet_results[0].boxes:
        for box in helmet_results[0].boxes:
            name = helmet_model.names[int(box.cls[0])]
            if name == 'helmet':
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                helmet_boxes.append((x1, y1, x2, y2))

    # Get tracked persons with IDs
    tracked_persons = []
    if track_results[0].boxes and track_results[0].boxes.id is not None:
        for box in track_results[0].boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            person_id = int(box.id[0])
            tracked_persons.append((person_id, x1, y1, x2, y2))

    # Track which IDs are currently in violation
    current_violating_ids = set()

    # Draw zone
    zx1, zy1, zx2, zy2 = ZONE
    cv2.rectangle(frame, (zx1, zy1), (zx2, zy2), (0, 255, 0), 2)
    cv2.putText(frame, 'LOADING ZONE', (zx1 + 5, zy1 + 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

    # Draw helmet boxes
    for hx1, hy1, hx2, hy2 in helmet_boxes:
        cv2.rectangle(frame, (hx1, hy1), (hx2, hy2), (255, 0, 0), 2)
        cv2.putText(frame, 'Helmet', (hx1, hy1 - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 0, 0), 1)

    # Process each tracked person
    for person_id, px1, py1, px2, py2 in tracked_persons:
        in_zone   = is_in_zone((px1, py1, px2, py2), ZONE)
        has_helmet = is_helmet_near((px1, py1, px2, py2), helmet_boxes)

        if in_zone and not has_helmet:
            current_violating_ids.add(person_id)

            # Check cooldown
            cooldown_ok = True
            if person_id in last_alert_frame:
                frames_since = frame_count - last_alert_frame[person_id]
                if frames_since < COOLDOWN_FRAMES:
                    cooldown_ok = False

            # New violation event
            if person_id not in active_violations and cooldown_ok:
                active_violations[person_id] = frame_count
                last_alert_frame[person_id]  = frame_count
                unique_events += 1
                print(f"Frame {frame_count}: NEW VIOLATION — Person ID {person_id} entered zone without helmet")

            # Draw RED box with ID
            cv2.rectangle(frame, (px1, py1), (px2, py2), (0, 0, 255), 3)
            cv2.putText(frame, f'ALERT ID:{person_id}', (px1, py1 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

            # Show duration if active
            if person_id in active_violations:
                duration = frame_count - active_violations[person_id]
                cv2.putText(frame, f'Duration: {duration}f', (px1, py2 + 15),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)

        elif in_zone and has_helmet:
            # Has helmet — draw YELLOW
            cv2.rectangle(frame, (px1, py1), (px2, py2), (0, 255, 255), 2)
            cv2.putText(frame, f'OK ID:{person_id}', (px1, py1 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)
        else:
            # Outside zone — WHITE
            cv2.rectangle(frame, (px1, py1), (px2, py2), (255, 255, 255), 1)
            cv2.putText(frame, f'ID:{person_id}', (px1, py1 - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)

    # Remove persons who left zone or put on helmet
    ended = []
    for pid in list(active_violations.keys()):
        if pid not in current_violating_ids:
            start  = active_violations[pid]
            dur    = frame_count - start
            violation_log.append({
                'person_id':   pid,
                'start_frame': start,
                'end_frame':   frame_count,
                'duration':    dur
            })
            ended.append(pid)
            print(f"Frame {frame_count}: VIOLATION ENDED — Person ID {pid} | Duration: {dur} frames")

    for pid in ended:
        del active_violations[pid]

    # Show event counter on frame
    cv2.putText(frame, f'Unique Events: {unique_events}', (10, height - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

    out.write(frame)
    cv2.imshow('OMNIX Tracked Alert', frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
out.release()
cv2.destroyAllWindows()

# Final report
print(f"\n{'='*50}")
print(f"FINAL REPORT")
print(f"{'='*50}")
print(f"Total frames processed : {frame_count}")
print(f"Unique violation events: {unique_events}")
print(f"\nViolation Event Details:")
real_events = [e for e in violation_log if e['duration'] >= 5]
print(f"\nFiltered events (duration >= 5 frames): {len(real_events)}")
for i, event in enumerate(real_events):
    print(f"  Event {i+1}: Person ID {event['person_id']} | "
          f"Start frame {event['start_frame']} | "
          f"Duration {event['duration']} frames")
print(f"\nOutput saved: tracked_alert_output.mp4")