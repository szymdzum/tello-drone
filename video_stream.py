#!/usr/bin/env python3
"""
Tello video stream with OpenCV face detection.

Works on the ground — no flight needed. Connect to Tello Wi-Fi and run:
    python video_stream.py

Controls (with video window focused):
    q       — quit
    f       — toggle face detection
    p       — take a screenshot (saved to tello-drone/captures/)
    s       — show current telemetry overlay
"""

import os
import sys
import time
from datetime import datetime

import cv2

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tello import Tello, TelloError

CAPTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "captures")


def main():
    os.makedirs(CAPTURES_DIR, exist_ok=True)

    drone = Tello()
    cap = None  # set once the stream opens; guarded in finally
    face_detect = True
    show_telemetry = True
    frame_count = 0
    fps = 0
    fps_start = time.time()

    # Load face detection model. cv2.data is valid at runtime; opencv-python
    # just ships incomplete type stubs, so the checker can't see it.
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"  # pyright: ignore[reportAttributeAccessIssue]
    face_cascade = cv2.CascadeClassifier(cascade_path)

    try:
        drone.connect()
        battery = drone.get_battery()
        print(f"Battery: {battery}%")

        # Start video stream
        drone.stream_on()
        print("Video stream ON")
        print()
        print("Opening video capture (may take a few seconds)...")
        print("Controls: q=quit  f=toggle faces  p=screenshot  s=telemetry")
        print()

        # Give the stream a moment to start
        time.sleep(2)

        # OpenCV capture from Tello's UDP video stream.
        # FFMPEG options tuned for reliable H.264 sync: a large probesize/
        # analyzeduration lets the decoder wait for a keyframe carrying the
        # SPS/PPS parameter sets before decoding. Do NOT add `fflags;nobuffer`
        # or a small probesize — joining mid-GOP then floods the log with
        # "non-existing PPS 0 referenced" / "no frame!" and never decodes.
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "timeout;10000000|analyzeduration;6000000|probesize;6000000"
        cap = cv2.VideoCapture("udp://0.0.0.0:11111?overrun_nonfatal=1&fifo_size=50000000", cv2.CAP_FFMPEG)

        if not cap.isOpened():
            print("Failed to open video stream.")
            print("Make sure you're connected to Tello Wi-Fi.")
            return

        print("Stream connected! Press 'q' in the video window to quit.")

        # Track consecutive failed reads for recovery
        fail_count = 0
        MAX_FAILS = 30

        while True:
            ret, frame = cap.read()
            if not ret:
                fail_count += 1
                if fail_count > MAX_FAILS:
                    print("Stream lost, reconnecting...")
                    cap.release()
                    time.sleep(1)
                    cap = cv2.VideoCapture("udp://0.0.0.0:11111?overrun_nonfatal=1&fifo_size=50000000", cv2.CAP_FFMPEG)
                    fail_count = 0
                continue
            fail_count = 0

            frame_count += 1

            # Calculate FPS
            elapsed = time.time() - fps_start
            if elapsed >= 1.0:
                fps = frame_count / elapsed
                frame_count = 0
                fps_start = time.time()

            # Face detection
            if face_detect:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = face_cascade.detectMultiScale(
                    gray, scaleFactor=1.3, minNeighbors=5, minSize=(30, 30)
                )
                for (x, y, w, h) in faces:
                    cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
                    # Center crosshair
                    cx, cy = x + w // 2, y + h // 2
                    cv2.drawMarker(
                        frame, (cx, cy), (0, 255, 0),
                        cv2.MARKER_CROSS, 20, 2
                    )

                face_text = f"Faces: {len(faces)}"
                cv2.putText(
                    frame, face_text, (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2
                )

            # Telemetry overlay
            if show_telemetry:
                state = drone.state
                bat = state.get("bat", "?")
                h = state.get("h", "?")
                temp = state.get("temph", "?")

                cv2.putText(
                    frame, f"FPS: {fps:.0f}", (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2
                )
                cv2.putText(
                    frame, f"Bat: {bat}%  H: {h}cm  Temp: {temp}C",
                    (10, frame.shape[0] - 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1
                )

            # Mode indicators
            modes = []
            if face_detect:
                modes.append("FACE")
            if show_telemetry:
                modes.append("TELEM")
            mode_text = " | ".join(modes)
            cv2.putText(
                frame, mode_text,
                (frame.shape[1] - 150, 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 255), 1
            )

            cv2.imshow("Tello Stream", frame)

            # Key handling
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            elif key == ord("f"):
                face_detect = not face_detect
                print(f"Face detection: {'ON' if face_detect else 'OFF'}")
            elif key == ord("p"):
                filename = f"tello_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
                filepath = os.path.join(CAPTURES_DIR, filename)
                cv2.imwrite(filepath, frame)
                print(f"Screenshot saved: {filepath}")
            elif key == ord("s"):
                show_telemetry = not show_telemetry
                print(f"Telemetry overlay: {'ON' if show_telemetry else 'OFF'}")

    except TelloError as e:
        print(f"\nTello error: {e}")
    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        print("Cleaning up...")
        try:
            drone.stream_off()
        except Exception:
            pass
        if cap is not None:
            cap.release()
        cv2.destroyAllWindows()
        drone.close()


if __name__ == "__main__":
    main()
