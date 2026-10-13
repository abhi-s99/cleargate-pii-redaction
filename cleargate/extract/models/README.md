# Bundled model files

| File | Source | Licence | sha256 |
|---|---|---|---|
| `face_detection_yunet_2023mar.onnx` | OpenCV Zoo, `models/face_detection_yunet/` (YuNet, Wu et al.), fetched 13 Oct 2026 from `github.com/opencv/opencv_zoo` | MIT (OpenCV Zoo model licence) | `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4` |

Loaded with `cv2.FaceDetectorYN` entirely offline (TR-SEC-01). Used next to the Haar
cascades required by TR-EX-06 because Haar misses small faces in screenshots (ADR-27).
