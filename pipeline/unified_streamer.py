"""
UnifiedStreamer — single ffmpeg process that streams annotated frames to MediaMTX
via RTMP and optionally records to a file simultaneously using the tee muxer.

Toggling recording restarts ffmpeg (~1-2 s stream gap) to add/remove the file
output. The RTMP stream is always active while the streamer is running.
"""

import logging
import os
import subprocess
from subprocess import PIPE
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


class UnifiedStreamer:
    def __init__(self, rtmp_url: str):
        self._rtmp_url = rtmp_url
        self._process: Optional[subprocess.Popen] = None
        self._fps: int = 25
        self._w: int = 0
        self._h: int = 0
        self._recording_path: Optional[str] = None

    def start(self, fps: int, width: int, height: int) -> None:
        self._fps = fps
        self._w = width
        self._h = height
        self._launch()

    def push(self, frame: np.ndarray) -> None:
        if self._process is None:
            return
        try:
            self._process.stdin.write(frame.tobytes())
            self._process.stdin.flush()
        except BrokenPipeError:
            logger.warning("ffmpeg pipe broken — process may have crashed")
            self._process = None

    def start_recording(self, output_path: str) -> None:
        logger.info("recording start → %s", output_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        self._terminate()
        self._recording_path = output_path
        self._launch()

    def stop_recording(self) -> None:
        logger.info("recording stop")
        self._terminate()
        self._recording_path = None
        self._launch()

    def stop(self) -> None:
        self._terminate()

    # ── internal ──────────────────────────────────────────────────────────────

    def _build_args(self) -> list:
        base = [
            "ffmpeg", "-y",
            "-f", "rawvideo", "-pix_fmt", "bgr24",
            "-s", f"{self._w}x{self._h}",
            "-r", str(self._fps),
            "-i", "pipe:0",
            "-c:v", "libx264", "-crf", "23", "-preset", "fast", "-bf", "0",
        ]
        if self._recording_path:
            return base + [
                "-f", "tee",
                f"[f=flv]{self._rtmp_url}|[f=mp4]{self._recording_path}",
            ]
        return base + ["-f", "flv", self._rtmp_url]

    def _launch(self) -> None:
        args = self._build_args()
        logger.info("launching ffmpeg | recording=%s", self._recording_path or "off")
        self._process = subprocess.Popen(args, stdin=PIPE, stdout=PIPE, stderr=PIPE)

    def _terminate(self) -> None:
        if self._process is None:
            return
        try:
            self._process.stdin.close()
        except Exception:
            pass
        self._process.wait()
        self._process = None
