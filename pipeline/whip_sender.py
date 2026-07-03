"""
WhipSender — pushes annotated video frames to a MediaMTX WHIP endpoint.

Runs an asyncio event loop in a background thread so the synchronous
pipeline frame loop can call send_frame() without blocking.
"""

import asyncio
import fractions
import logging
import threading
import time
from typing import Optional

import aiohttp
import av
import numpy as np
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from aiortc.mediastreams import MediaStreamError

logger = logging.getLogger(__name__)

VIDEO_CLOCK_RATE = 90_000
VIDEO_TIME_BASE = fractions.Fraction(1, VIDEO_CLOCK_RATE)


class FrameTrack(VideoStreamTrack):
    """Feeds frames from a thread-safe queue into the WebRTC video track."""

    def __init__(self, fps: float = 25.0):
        super().__init__()
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=2)
        self._start: Optional[float] = None
        self.frames_dropped: int = 0

    async def recv(self) -> av.VideoFrame:
        try:
            ndarray = await asyncio.wait_for(self._queue.get(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("frame queue timed out — no frame received in 5 s")
            raise MediaStreamError("frame queue timed out")

        # Stamp PTS from actual wall-clock time so the browser sees accurate
        # inter-frame spacing — avoids jitter buffer confusion when inference
        # is slower than the originally declared FPS.
        now = time.time()
        if self._start is None:
            self._start = now
        pts = int((now - self._start) * VIDEO_CLOCK_RATE)

        frame = av.VideoFrame.from_ndarray(ndarray, format="bgr24")
        frame.pts = pts
        frame.time_base = VIDEO_TIME_BASE
        return frame


class WhipSender:
    """Establishes a WHIP connection to MediaMTX and streams frames via WebRTC."""

    def __init__(self, whip_url: str, fps: float = 25.0):
        self._whip_url = whip_url
        self._fps = fps
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._track: Optional[FrameTrack] = None
        self._pc: Optional[RTCPeerConnection] = None
        self._alive: bool = False

    def start(self) -> None:
        logger.info("starting WhipSender → %s", self._whip_url)
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, name="whip-loop", daemon=True
        )
        self._thread.start()
        future = asyncio.run_coroutine_threadsafe(self._connect(), self._loop)
        future.result(timeout=15)

    async def _connect(self) -> None:
        logger.debug("creating RTCPeerConnection and FrameTrack")
        self._track = FrameTrack(fps=self._fps)
        self._pc = RTCPeerConnection()
        self._pc.addTrack(self._track)

        offer = await self._pc.createOffer()
        await self._pc.setLocalDescription(offer)

        logger.debug("sending WHIP offer to %s", self._whip_url)
        async with aiohttp.ClientSession() as session:
            async with session.post(
                self._whip_url,
                data=self._pc.localDescription.sdp,
                headers={"Content-Type": "application/sdp"},
            ) as resp:
                if resp.status not in (200, 201):
                    body = await resp.text()
                    raise RuntimeError(
                        f"WHIP handshake failed: HTTP {resp.status} — {body[:200]}"
                    )
                answer_sdp = await resp.text()

        await self._pc.setRemoteDescription(
            RTCSessionDescription(sdp=answer_sdp, type="answer")
        )
        self._alive = True
        logger.info("WHIP session established → %s", self._whip_url)

        @self._pc.on("connectionstatechange")
        async def _on_state():
            state = self._pc.connectionState if self._pc else "unknown"
            if state in ("failed", "closed", "disconnected"):
                logger.warning("WebRTC connection state → %s", state)
                self._alive = False
            else:
                logger.debug("WebRTC connection state → %s", state)

    def is_alive(self) -> bool:
        return self._alive and bool(self._loop and self._loop.is_running())

    def send_frame(self, frame: np.ndarray) -> None:
        if not (self._track and self._loop and self._loop.is_running()):
            return
        q = self._track._queue
        track = self._track

        def _enqueue() -> None:
            # Drop the oldest frame if the consumer (WebRTC) hasn't caught up.
            # Runs on the event loop thread so asyncio.Queue ops are safe.
            if q.full():
                try:
                    q.get_nowait()
                    track.frames_dropped += 1
                    logger.debug("frame dropped from queue (consumer behind)")
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait(frame)

        self._loop.call_soon_threadsafe(_enqueue)

    def stop(self) -> None:
        logger.info("stopping WhipSender")
        if self._pc and self._loop:
            future = asyncio.run_coroutine_threadsafe(self._pc.close(), self._loop)
            try:
                future.result(timeout=5)
            except Exception:
                pass
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=5)
        logger.debug("WhipSender stopped")
