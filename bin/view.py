#!/usr/bin/env python3
"""
Quick pipeline viewer — runs inference and serves annotated frames as MJPEG.

Open http://localhost:8080/ in a browser to view the live stream.
No MediaMTX or WebRTC required.

Usage:
    python bin/view.py [--weights path/to/weights.pth] [--port 8080]

Environment variables:
    CONFIG_PATH     Path to sources config JSON (default: config/sources.json)
    MODEL_WEIGHTS   Path to .pth weights file
    VIEWER_PORT     HTTP port to serve MJPEG on (default: 8080)
"""

import argparse
import os
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import cv2
import supervision as sv
from inference import InferencePipeline
from inference.core.interfaces.camera.entities import VideoFrame
from inference.core.interfaces.camera.video_source import (
    BufferConsumptionStrategy,
    BufferFillingStrategy,
)
from rfdetr import RFDETRNano

from config_manager.ConfigManager import ConfigManager

# ── shared frame state ─────────────────────────────────────────────────────
_latest_jpeg: bytes = b""
_frame_lock = threading.Lock()
_frame_event = threading.Condition(_frame_lock)

# ── inference state (populated in main before pipeline starts) ─────────────
_model: RFDETRNano = None
_tracker: sv.ByteTrack = None
_trace_ann: sv.TraceAnnotator = None
_box_ann: sv.BoxAnnotator = None

HTML = b"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Pipeline Viewer</title>
  <style>
    body { margin: 0; background: #111; display: flex; align-items: center; justify-content: center; height: 100vh; }
    img  { max-width: 100%; max-height: 100vh; object-fit: contain; }
  </style>
</head>
<body>
  <img src="/stream">
</body>
</html>"""


def _on_video_frame(video_frames: list[VideoFrame]) -> list:
    frame = video_frames[0].image  # BGR ndarray
    results = _model.predict(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), threshold=0.5)
    detections = _tracker.update_with_detections(results)
    annotated = frame.copy()
    annotated = _trace_ann.annotate(scene=annotated, detections=detections)
    annotated = _box_ann.annotate(scene=annotated, detections=detections)
    _, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 80])
    with _frame_event:
        global _latest_jpeg
        _latest_jpeg = buf.tobytes()
        _frame_event.notify_all()
    return [None]


class _MjpegHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(HTML)
        elif self.path == "/stream":
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            try:
                while True:
                    with _frame_event:
                        _frame_event.wait(timeout=2.0)
                        jpeg = _latest_jpeg
                    if not jpeg:
                        continue
                    self.wfile.write(
                        b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
                    )
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *_):
        pass


def main() -> None:
    global _model, _tracker, _trace_ann, _box_ann

    parser = argparse.ArgumentParser(description="Pipeline MJPEG viewer")
    parser.add_argument("--weights", default=os.getenv("MODEL_WEIGHTS", "rf-detr-nano.pth"))
    parser.add_argument("--port", type=int, default=int(os.getenv("VIEWER_PORT", "8080")))
    args = parser.parse_args()

    config_path = os.getenv("CONFIG_PATH", "config/sources.json")
    config = ConfigManager(sources_config_path=config_path)
    if not config.sources.active_sources:
        print("ERROR: no active camera source in config", file=sys.stderr)
        sys.exit(1)
    rtsp_url = config.sources.active_sources[0].ip_address

    print(f"Loading model: {args.weights}", flush=True)
    _model = RFDETRNano(pretrain_weights=args.weights)
    _tracker = sv.ByteTrack()
    _trace_ann = sv.TraceAnnotator(thickness=4)
    _box_ann = sv.BoxAnnotator(thickness=4)

    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;udp"

    pipeline = InferencePipeline.init_with_custom_logic(
        video_reference=rtsp_url,
        on_video_frame=_on_video_frame,
        source_buffer_filling_strategy=BufferFillingStrategy.DROP_OLDEST,
        source_buffer_consumption_strategy=BufferConsumptionStrategy.EAGER,
        video_source_properties={"BUFFERSIZE": 1.0},
    )

    server = HTTPServer(("0.0.0.0", args.port), _MjpegHandler)
    threading.Thread(target=server.serve_forever, daemon=True, name="mjpeg").start()

    print(f"\n  Stream → http://localhost:{args.port}/\n", flush=True)

    def _shutdown(sig, _frame):
        print("\nShutting down…", flush=True)
        pipeline.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    pipeline.start(use_main_thread=True)


if __name__ == "__main__":
    main()
