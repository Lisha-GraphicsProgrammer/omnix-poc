import cv2

cap = cv2.VideoCapture('site_video.mp4')

# Read frame 100 where workers are visible
cap.set(cv2.CAP_PROP_POS_FRAMES, 100)
ret, frame = cap.read()

print(f"Video size: {frame.shape[1]} x {frame.shape[0]}")

# Show frame with coordinate display on mouse click
def show_coords(event, x, y, flags, param):
    if event == cv2.EVENT_MOUSEMOVE:
        img = frame.copy()
        cv2.putText(img, f"X:{x} Y:{y}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        cv2.imshow('Find Zone Coordinates', img)

cv2.imshow('Find Zone Coordinates', frame)
cv2.setMouseCallback('Find Zone Coordinates', show_coords)

print("Move mouse over the video to see coordinates")
print("Press Q to quit")
cv2.waitKey(0)
cv2.destroyAllWindows()
cap.release()