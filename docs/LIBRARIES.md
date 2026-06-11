# Tello Drone — Useful GitHub Libraries

## Core Control Libraries

### DJITelloPy ⭐ 1,467
https://github.com/damiafuentes/DJITelloPy
**The go-to library.** Full SDK implementation, video streaming, state parsing, swarm support.
`pip install djitellopy` — Python 3.6+, depends on opencv-python + av.
Use for: everything. Replaces raw socket code when you want reliability.

### Tello-Python ⭐ 1,442
https://github.com/dji-sdk/Tello-Python
**Official DJI sample code.** Includes Single_Tello_Test, Tello_Video, and pose recognition demo.
Python 2.7 (dated), but good reference for understanding the protocol.

### TelloPy ⭐ 712
https://github.com/hanyazou/TelloPy
**Reverse-engineered low-level protocol.** Goes beyond the text SDK — accesses
internal drone commands. Includes joystick + video examples.
Use for: deeper hardware access, gamepad control, understanding the binary protocol.

### microlinux/tello ⭐ 172
https://github.com/microlinux/tello
**Minimal, clean Python interface.** Good reference for a lightweight wrapper.

## Computer Vision & AI

### tello-gesture-control ⭐ 341
https://github.com/kinivi/tello-gesture-control
**Hand gesture → flight control.** Uses MediaPipe for hand tracking.
Great starter for gesture-based projects.

### tello-openpose ⭐ 306
https://github.com/geaxgx/tello-openpose
**Body pose detection** using OpenPose. Fly the drone with body movements.

### Tello-Object-Tracking ⭐ 117
https://github.com/murtazahassan/Tello-Object-Tracking
**Object tracking with OpenCV.** Follow colored objects or faces.
Simple and well-documented — good first CV project.

### TelloTV ⭐ 209
https://github.com/Jabrils/TelloTV
**AI-powered Tello.** Autonomous flight with neural networks.

## Robotics / ROS

### tello_ros ⭐ 228
https://github.com/clydemcqueen/tello_ros
**ROS2 driver.** Full integration with the ROS ecosystem (Foxy + Gazebo).

### tello-ros2 ⭐ 211
https://github.com/tentone/tello-ros2
**ROS2 + Visual SLAM.** Indoor mapping using the Tello camera.

### Tello_ROS_ORBSLAM ⭐ 194
https://github.com/tau-adl/Tello_ROS_ORBSLAM
**Full framework** — ROS + ORB-SLAM for 3D mapping with Tello.

## Multi-Drone / Swarm

### Multi-Tello-Formation ⭐ 196
https://github.com/TelloSDK/Multi-Tello-Formation
**Official multi-drone swarm** code. Requires Tello EDU.

## Fun / Alternative Interfaces

### drone-keyboard ⭐ 158
https://github.com/dnomak/drone-keyboard
**Browser-based keyboard control.** Fly the Tello from a web page.

### DroneBlocks-Tello-Python ⭐ 152
https://github.com/dbaldwin/DroneBlocks-Tello-Python
**Beginner-friendly course** — structured Python scripts for learning.

### scratch3-tello ⭐ 98
https://github.com/kebhr/scratch3-tello
**Scratch 3.0 integration.** Visual block programming for the Tello.

### tello-nodejs ⭐ 94
https://github.com/jsolderitsch/tello-nodejs
**Node.js interface.** If you prefer JavaScript.

## Project Building Blocks (pip packages)

These are the pip packages that turn the [ideas list](IDEAS.md) into working code,
mapped to the project they unlock.

### Computer Vision & Perception
- **opencv-contrib-python** — OpenCV *plus* the `aruco` module and extra trackers.
  Use this instead of `opencv-python` if you want **ArUco/marker navigation**.
  `pip install opencv-contrib-python` (don't install both — they conflict).
- **mediapipe** — Google's hand / pose / face-mesh tracking. Powers **gesture
  control** and **body-pose flying**. `pip install mediapipe`.
- **ultralytics** — YOLO11/YOLOv8 object detection in ~3 lines. Drop-in for the
  **face/object tracker** and **pet tracker** ideas. `pip install ultralytics`.
- **pupil-apriltags** — fast AprilTag detector (more robust than ArUco for
  **waypoint markers**). `pip install pupil-apriltags`.
- **numpy** — pulled in by everything above; the array backbone for any frame or
  sensor math. `pip install numpy`.

### Control Theory & State Estimation
- **simple-pid** — tiny, well-tested PID loop. The **PID stabilizer** /
  **object-follower** idea without hand-rolling the controller.
  `pip install simple-pid`.
- **filterpy** — Kalman filters, EKF/UKF, and sensor-fusion building blocks for
  the **IMU + baro + ToF fusion** and **dead-reckoning waypoint** ideas.
  `pip install filterpy`.

### Video Decoding (alternative to OpenCV's FFMPEG backend)
- **av** (PyAV) — Python bindings to FFmpeg. Decode the raw H.264 UDP stream
  frame-by-frame with lower latency than `cv2.VideoCapture`. This is what
  DJITelloPy uses under the hood. `pip install av`.

### Input & Interfaces
- **pygame** — gamepad/keyboard polling + a window for live video. The
  **keyboard/gamepad pilot**. `pip install pygame`.
- **inputs** — lightweight cross-platform gamepad reader if you don't want all of
  pygame. `pip install inputs`.
- **vosk** — offline speech recognition (no cloud, no API key) for **voice
  control**. `pip install vosk` + a small model download.
- **flask** — minimal web server for a **browser-based controller** (cf.
  drone-keyboard above). `pip install flask`.

## Recommended Install Order
1. `pip install djitellopy` — primary control library
2. `pip install opencv-contrib-python` — video stream + CV + ArUco markers
3. `pip install mediapipe` — hand/pose tracking (for gesture projects)
4. `pip install pygame` — gamepad/keyboard control
5. `pip install simple-pid filterpy` — control loops + sensor fusion
6. `pip install ultralytics` — object detection (heavier; install when needed)
