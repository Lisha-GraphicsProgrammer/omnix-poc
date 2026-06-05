import cv2
from ultralytics import YOLO

person_model = YOLO('yolov8n.pt')
helmet_model = YOLO('runs/detect/helmet_model/weights/best.pt')

cap = cv2.VideoCapture('site_video.mp4')
width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
fps    = int(cap.get(cv2.CAP_PROP_FPS))

out = cv2.VideoWriter(
    'zone_alert_output.mp4',
    cv2.VideoWriter_fourcc(*'mp4v'),
    fps, (width, height)
)

ZONE = (10, 10, 350, 470)

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

frame_count = 0
alert_count = 0
last_alert_frame = -30

print("Processing video...")

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        break

    frame_count += 1

    person_results = person_model(frame, classes=[0], conf=0.3, verbose=False)
    helmet_results = helmet_model(frame, conf=0.3, verbose=False)

    person_boxes = []
    if person_results[0].boxes:
        for box in person_results[0].boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            person_boxes.append((x1, y1, x2, y2))

    helmet_boxes = []
    if helmet_results[0].boxes:
        for box in helmet_results[0].boxes:
            name = helmet_model.names[int(box.cls[0])]
            if name == 'helmet':
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                helmet_boxes.append((x1, y1, x2, y2))

    zx1, zy1, zx2, zy2 = ZONE
    cv2.rectangle(frame, (zx1, zy1), (zx2, zy2), (0, 255, 0), 2)
    cv2.putText(frame, 'LOADING ZONE', (zx1 + 5, zy1 + 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

    for hx1, hy1, hx2, hy2 in helmet_boxes:
        cv2.rectangle(frame, (hx1, hy1), (hx2, hy2), (255, 0, 0), 2)
        cv2.putText(frame, 'Helmet', (hx1, hy1 - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 0, 0), 1)

    for px1, py1, px2, py2 in person_boxes:
        in_zone = is_in_zone((px1, py1, px2, py2), ZONE)
        has_helmet = is_helmet_near((px1, py1, px2, py2), helmet_boxes)

        if in_zone and not has_helmet:
            cv2.rectangle(frame, (px1, py1), (px2, py2), (0, 0, 255), 3)
            cv2.putText(frame, 'ALERT: NO HELMET!', (px1, py1 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
            if frame_count - last_alert_frame >= 30:
                alert_count += 1
                last_alert_frame = frame_count
                print(f"Frame {frame_count}: ALERT — worker without helmet in zone!")
        elif in_zone and has_helmet:
            cv2.rectangle(frame, (px1, py1), (px2, py2), (0, 255, 255), 2)
            cv2.putText(frame, 'OK: Has Helmet', (px1, py1 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)
        else:
            cv2.rectangle(frame, (px1, py1), (px2, py2), (255, 255, 255), 1)

    out.write(frame)
    cv2.imshow('OMNIX Zone Alert', frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
out.release()
cv2.destroyAllWindows()

print(f"\nDone! Processed {frame_count} frames")
print(f"Total alerts fired: {alert_count}")
print(f"Output saved: zone_alert_output.mp4")