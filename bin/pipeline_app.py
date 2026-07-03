#!/usr/bin/env python
"""Pipeline process for the sheep counter.

Reads the active camera from config/sources.json, runs the RF-DETR inference
pipeline, annotates frames with bounding boxes and line-crossing counts, and
re-publishes via aiortc → MediaMTX (WHIP → WebRTC/WHEP for the browser).

A background thread posts a heartbeat metric to the API server every
HEARTBEAT_INTERVAL_S seconds so the frontend WebSocket can reflect live status.

Usage:
    python bin/pipeline_app.py [--weights rf-detr-nano.pth] [--log-level debug]

Environment variables (all optional):
    MODEL_WEIGHTS         Path to .pth weights file (default: rf-detr-nano.pth)
    CONFIG_PATH           Path to sources config JSON (default: config/sources.json)
    WHIP_URL              WHIP push destination (default: http://localhost:8889/live/whip)
    API_BASE_URL          API server base URL (default: http://localhost:8000)
    HEARTBEAT_INTERVAL_S  Seconds between heartbeat posts (default: 5)
    PIPELINE_REFRESH_PORT Port for config-refresh HTTP server (default: 8001)
    LOG_LEVEL             Logging level: debug|info|warning|error (default: info)
"""

import argparse
import logging
import os
import signal
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests

from pipeline.pipeline import Pipeline

CONFIG_PATH = os.getenv("CONFIG_PATH", "config/sources.json")
RTMP_URL = os.getenv("RTMP_URL", "rtmp://localhost:1935/live")
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
PIPELINE_REFRESH_PORT = int(os.getenv("PIPELINE_REFRESH_PORT", "8001"))
HEARTBEAT_INTERVAL_S = float(os.getenv("HEARTBEAT_INTERVAL_S", "5"))


def _setup_logging(level_str: str) -> None:
    level = getattr(logging, level_str.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )


logger = logging.getLogger(__name__)


def _start_refresh_server(pipeline: Pipeline) -> None:
    class RefreshHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path == "/refresh":
                logger.info("config refresh triggered via HTTP")
                pipeline.request_config_refresh()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ok":true}')
            elif self.path == "/record":
                logger.info("count record triggered via HTTP")
                pipeline.request_count_record()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ok":true}')
            elif self.path == "/recording/start":
                logger.info("recording start triggered via HTTP")
                pipeline.request_recording_start()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ok":true}')
            elif self.path == "/recording/stop":
                logger.info("recording stop triggered via HTTP")
                pipeline.request_recording_stop()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ok":true}')
            else:
                logger.debug("refresh server: unk1nown path %s", self.path)
                self.send_response(404)
                self.end_headers()

        def log_message(self, *args):
            pass  # handled by our logger above

    class ReuseAddrHTTPServer(HTTPServer):
        allow_reuse_address = True

    server = ReuseAddrHTTPServer(("0.0.0.0", PIPELINE_REFRESH_PORT), RefreshHandler)
    logger.info("config refresh server listening on port %d", PIPELINE_REFRESH_PORT)
    threading.Thread(target=server.serve_forever, daemon=True, name="refresh-server").start()


def _post_pipeline_metric(payload: dict) -> None:
    try:
        requests.post(
            f"{API_BASE_URL}/api/internal/pipeline-metric",
            json=payload,
            timeout=2,
        )
    except Exception as exc:
        logger.debug("heartbeat post failed: %s", exc)


def _heartbeat_loop(pipeline: Pipeline, stop_event: threading.Event) -> None:
    logger.debug("heartbeat loop started (interval=%.1f s)", HEARTBEAT_INTERVAL_S)
    while not stop_event.wait(HEARTBEAT_INTERVAL_S):
        payload = {
            "heartbeat": datetime.now(timezone.utc).isoformat(),
            "fps": pipeline.get_fps(),
            "latencyMs": pipeline.get_latency_ms(),
            "counts": pipeline.get_counts(),
        }
        logger.debug(
            "heartbeat | fps=%.1f latency=%.0f ms counts=%s",
            payload["fps"],
            payload["latencyMs"],
            payload["counts"],
        )
        _post_pipeline_metric(payload)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sheep counter inference pipeline")
    parser.add_argument(
        "--weights",
        default=os.getenv("MODEL_WEIGHTS", "rf-detr-nano.pth"),
        help="Path to model weights (.pth file)",
    )
    parser.add_argument(
        "--log-level",
        default=os.getenv("LOG_LEVEL", "info"),
        choices=["debug", "info", "warning", "error"],
        help="Logging verbosity",
    )
    args = parser.parse_args()

    _setup_logging(args.log_level)

    logger.info(
        "pipeline starting | weights=%s rtmp=%s api=%s refresh_port=%d",
        args.weights,
        RTMP_URL,
        API_BASE_URL,
        PIPELINE_REFRESH_PORT,
    )

    pipeline = Pipeline(
        config_path=CONFIG_PATH,
        model_chkpt_filepath=args.weights,
        rtmp_url=RTMP_URL,
    )

    stop_event = threading.Event()

    def _shutdown(sig, _frame):
        logger.info("received signal %d — shutting down", sig)
        stop_event.set()
        pipeline.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    _start_refresh_server(pipeline)

    heartbeat_thread = threading.Thread(
        target=_heartbeat_loop,
        args=(pipeline, stop_event),
        name="heartbeat",
        daemon=True,
    )
    heartbeat_thread.start()

    logger.info("pipeline running")
    pipeline.start()  # blocking
    return 0


if __name__ == "__main__":
    sys.exit(main())
