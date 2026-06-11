# Tello Drone Project Ideas

## Hardware Specs to Work With
- Control: Full 3D movement via UDP, RC joystick mode ~50Hz
- Camera: 720p H.264 video stream (UDP port 11111)
- Sensors: IMU (pitch/roll/yaw), barometer, ToF distance, temperature
- Compute: All processing on host machine — drone is just an actuator
- Limits: No GPS, no onboard storage, ~13 min flight, ~100m Wi-Fi range

## Computer Vision (Camera + OpenCV)
- **Face/object tracker** — detect target with OpenCV/YOLO, send `rc` commands to follow
- **Gesture control** — MediaPipe hand tracking to fly with hand gestures
- **QR/ArUco marker navigation** — place markers, drone reads them and navigates between waypoints
- **Line follower** — camera down, detect colored tape, follow it airborne
- **Room mapper** — fly sweep pattern, stitch frames into overhead map

## Automation / Autonomous Flight
- **Patrol bot** — scripted repeating flight path (fly perimeter, photograph, land, report)
- **Inventory scanner** — fly along shelves, photograph labels, OCR them
- **Obstacle avoidance** — ToF sensor + camera to detect and avoid objects
- **Waypoint system** — dead-reckoning position tracker using IMU + baro + ToF

## Robotics / Control Theory
- **PID controller** — stabilization loop using `rc` + telemetry feedback
- **Kalman filter** — fuse IMU + barometer + ToF for smooth state estimation
- **Swarm coordination** (Tello EDU only) — multiple drones, coordinated patterns
- **Throw & catch** — `throwfly` + IMU to detect throw and auto-stabilize

## Fun / Creative
- **Keyboard/gamepad pilot** — pygame/curses real-time controller with live video
- **Voice control** — speech recognition → command mapping
- **Pet tracker** — detect dog/cat via camera, follow around the house
- **Time-lapse bot** — hover, periodic photos, stitch into timelapse

## Learning Value
- Networking: raw UDP sockets, client-server
- Multithreading: concurrent command/state/video channels
- Control systems: PID loops, RC mapping
- Computer vision: real-time frame processing
- State estimation: sensor fusion, dead reckoning
- Robotics architecture: Sense → Plan → Act loop
- Protocol design: text-based command protocol, state parsing
