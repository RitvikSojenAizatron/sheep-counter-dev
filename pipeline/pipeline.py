import cv2
import json
import logging
import os
import subprocess
from subprocess import PIPE
import threading
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

import numpy as np
import supervision as sv

from inference import InferencePipeline
from inference.core.interfaces.camera.entities import VideoFrame
from inference.core.interfaces.stream.inference_pipeline import SinkMode
from rfdetr import RFDETRNano

from config_manager.ConfigManager import ConfigManager
from pipeline.whip_sender import WhipSender

from ultralytics import YOLO

logger = logging.getLogger(__name__)


class FrameBuffer:
    """Manager Class that pushes frames to ffmpeg process for recording functionality"""

    def __init__(
        self
    ):
        self.process = None


    def start(self, output_path: str, fps: int, frame_width: int, frame_height: int) -> None:
        self.process = subprocess.Popen([
            "ffmpeg", "-y",
            "-f", "rawvideo",
            "-pix_fmt", "bgr24",
            "-s", f"{frame_width}x{frame_height}",
            "-r", str(fps),
            "-i", "pipe:0",
            "-c:v", "libx264",
            "-crf", "23",
            "-preset", "fast",
            output_path,
        ], stdin=PIPE, stdout=PIPE, stderr=PIPE)

    def push(self, frame: np.ndarray) -> None:
        if self.process is None:
            logger.warning("no ffmpeg process started, cannot push frame")
            return
        self.process.stdin.write(frame.tobytes())
        self.process.stdin.flush()

    def stop(self) -> None:
        if self.process is None:
            return
        self.process.stdin.close()
        self.process.wait()
        self.process = None


class WhipSink:
    """Callable sink that receives raw predictions from InferencePipeline's
    on_prediction hook, annotates frames, updates line zones, and forwards
    the result to MediaMTX via WHIP."""

    def __init__(
        self,
        whip_url: str,
        byte_tracker: sv.ByteTrack,
        trace_annotator: sv.TraceAnnotator,
        bounding_box_annotator: sv.BoxAnnotator,
        line_zone_annotator: sv.LineZoneAnnotator,
        dot_annotator: sv.DotAnnotator,
        get_linezones,
    ):
        self._whip_url = whip_url
        self._byte_tracker = byte_tracker
        self._trace_annotator = trace_annotator
        self._bounding_box_annotator = bounding_box_annotator
        self._line_zone_annotator = line_zone_annotator
        self._dot_annotator = dot_annotator
        self._get_linezones = get_linezones
        self._sender: Optional[WhipSender] = None
        self._fps: float = 25.0
        self._recreations: int = 0
        self._frame_buffer = FrameBuffer()

    # ── InferencePipeline sink interface ─────────────────────────────────────

    def __call__(self, predictions: List[sv.Detections], video_frames: List[VideoFrame]) -> None:
        if not video_frames:
            return

        linezones = self._get_linezones()

        for detections, video_frame in zip(predictions, video_frames):
            annotated = video_frame.image.copy()

            annotated = self._trace_annotator.annotate(scene=annotated, detections=detections)
            annotated = self._dot_annotator.annotate(scene=annotated, detections=detections)

            self._draw_counts(annotated, linezones)

            logger.info("COUNTS DRAWN")

            self._forward(annotated)

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def stop(self) -> None:
        if self._sender:
            self._sender.stop()
            self._sender = None

    # ── overlay ───────────────────────────────────────────────────────────────

    @staticmethod
    def _draw_counts(frame: np.ndarray, linezones: dict) -> None:
        font = cv2.FONT_HERSHEY_SIMPLEX
        scale = 0.7
        thickness = 2
        pad = 10
        line_h = 28
        cyan = (255, 255, 0)  # BGR

        text_lines = []
        for name, zone in linezones.items():
            start = (int(zone.vector.start.x), int(zone.vector.start.y))
            end = (int(zone.vector.end.x), int(zone.vector.end.y))
            mid = ((start[0] + end[0]) // 2, (start[1] + end[1]) // 2)

            cv2.line(frame, start, end, cyan, 2, cv2.LINE_AA)
            cv2.circle(frame, start, 5, cyan, -1)
            cv2.circle(frame, end, 5, cyan, -1)
            cv2.putText(frame, "gate", (mid[0], mid[1] - 6), font, scale, cyan, thickness, cv2.LINE_AA)

            text_lines.append(f"line_stats: in:{zone.in_count}  out:{zone.out_count}")

        if not text_lines:
            return

        text_w = max(cv2.getTextSize(l, font, scale, thickness)[0][0] for l in text_lines)
        block_h = line_h * len(text_lines) + pad
        x = frame.shape[1] - text_w - pad * 2
        cv2.rectangle(frame, (x - pad, pad), (frame.shape[1] - pad, pad + block_h),
                      (0, 0, 0), -1)

        for i, text in enumerate(text_lines):
            y = pad + line_h * (i + 1)
            cv2.putText(frame, text, (x, y), font, scale, (255, 255, 255), thickness, cv2.LINE_AA)

    # ── stats ─────────────────────────────────────────────────────────────────

    @property
    def recreations(self) -> int:
        return self._recreations

    @property
    def frames_dropped(self) -> int:
        if self._sender and self._sender._track:
            return self._sender._track.frames_dropped
        return 0

    # ── internal ──────────────────────────────────────────────────────────────

    def _forward(self, frame: np.ndarray) -> None:
        if self._sender is not None and not self._sender.is_alive():
            logger.warning(
                "WhipSender connection lost — recreating (#%d)", self._recreations + 1
            )
            self._sender.stop()
            self._sender = None
            self._recreations += 1

        if self._sender is None:
            logger.info("creating WhipSender (fps=%.1f)", self._fps)
            self._sender = WhipSender(whip_url=self._whip_url, fps=self._fps)
            self._sender.start()

        self._sender.send_frame(frame)


class Pipeline:
    """Reads an RTSP stream via InferencePipeline, runs RF-DETR inference on each
    frame, annotates with bounding boxes and line-crossing counts, then re-publishes
    the annotated stream via WebRTC/WHIP to MediaMTX."""

    def __init__(
        self,
        config_path: str,
        model_chkpt_filepath: str,
        whip_url: str = "http://localhost:8889/live/whip",
    ):
        self._inference_pipeline: Optional[InferencePipeline] = None

        # Lock guards self.linezones, which is read on the inference thread and
        # written on the HTTP refresh thread.
        self._linezones_lock = threading.Lock()
        self.linezones: Dict[str, sv.LineZone] = {}

        self._current_fps: float = 0.0
        self._frame_latency_ms: float = 0.0

        # Stats tracking for periodic INFO summaries.
        self._frame_count: int = 0
        self._frames_since_log: int = 0
        self._last_stats_log: float = 0.0

        logger.info("loading config from %s", config_path)
        self.config_manager = ConfigManager(sources_config_path=config_path)
        if not self.config_manager.sources.active_sources:
            raise RuntimeError("No active camera source found in config.")

        #load in model using config
        #self._model = load_model(self.config_manager.)

        #logger.info("loading model weights from %s", model_chkpt_filepath)
        self.model = RFDETRNano(pretrain_weights=model_chkpt_filepath)

        #load in yolov8 model
        #self.model = YOLO('/home/ritvik-sojen/code/Counting-Sheep/sheep_counter_full/models/yolov8m_all_finetune.pt')
        logger.info("model loaded")

        self.byte_tracker = sv.ByteTrack()
        self.trace_annotator = sv.TraceAnnotator(thickness=4)
        self.bounding_box_annotator = sv.BoxAnnotator(thickness=4)
        self.dot_annotator = sv.DotAnnotator()
        self.line_zone_annotator = sv.LineZoneAnnotator(
            thickness=4, text_thickness=4, text_scale=2
        )

        self._whip_sink = WhipSink(
            whip_url=whip_url,
            byte_tracker=self.byte_tracker,
            trace_annotator=self.trace_annotator,
            bounding_box_annotator=self.bounding_box_annotator,
            line_zone_annotator=self.line_zone_annotator,
            dot_annotator=self.dot_annotator,
            get_linezones=self._snapshot_linezones,
        )

        self._recording_state = False
        self._frame_buffer = FrameBuffer()

    # ── public metrics ────────────────────────────────────────────────────────

    def get_fps(self) -> float:
        return self._current_fps

    def get_latency_ms(self) -> float:
        return self._frame_latency_ms

    def get_counts(self) -> Dict[str, Dict[str, int]]:
        with self._linezones_lock:
            return {
                lid: {"in": z.in_count, "out": z.out_count}
                for lid, z in self.linezones.items()
            }

    # ── main loop ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        self._rebuild_linezones()

        active = self.config_manager.sources.active_sources
        rtsp_url = active[0].ip_address

        logger.info("starting InferencePipeline on %s", rtsp_url)
        self._inference_pipeline = InferencePipeline.init_with_custom_logic(
            video_reference=rtsp_url,
            on_video_frame=self._on_video_frame,
            on_prediction=self._whip_sink,
            sink_mode=SinkMode.BATCH
        )
        self._last_stats_log = time.time()
        self._inference_pipeline.start(use_main_thread=True)

    def stop(self) -> None:
        logger.info("stopping pipeline (total frames=%d)", self._frame_count)
        if self._inference_pipeline:
            self._inference_pipeline.terminate()
            self._inference_pipeline.join()
            self._inference_pipeline = None
        self._whip_sink.stop()
        logger.info("pipeline stopped")

    # ── frame callback ────────────────────────────────────────────────────────

    def _on_video_frame(self, video_frames: List[VideoFrame]) -> List[Any]:
        last = video_frames[-1]
        if last.measured_fps:
            self._current_fps = last.measured_fps
        elif last.fps:
            self._current_fps = last.fps

        t0 = time.perf_counter()
        self._frame_latency_ms = (time.perf_counter() - t0) * 1000 / len(video_frames)

        #list of detections
        detections=[]

        self._frame_count += len(video_frames)
        self._frames_since_log += len(video_frames)
        logger.debug(
            "batch %d frames | fps=%.1f latency=%.0f ms/frame",
            len(video_frames),
            self._current_fps,
            self._frame_latency_ms,
        )
        self._maybe_log_stats()

        #extract images into list
        images = [video_frame.image for video_frame in video_frames]

        linezones = self._snapshot_linezones()

        for image in images:
            #perform model inference and line crossing logic
            #predictions = sv.Detections.from_ultralytics(self.model(image, conf=0.5)[0])
            predictions = self.model.predict(image, threshold=0.5)
            detection = self.byte_tracker.update_with_detections(predictions)
         
            for zone in linezones.values():
                zone.trigger(detection)

            detections.append(detection)


            if self._recording_state:
                h, w = image.shape[:2]
                if self._frame_buffer.process is None:
                    os.makedirs("recordings", exist_ok=True)
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    output_path = os.path.join("recordings", f"{ts}.mp4")
                    self._frame_buffer.start(output_path, int(self._current_fps) or 25, w, h)
                self._frame_buffer.push(image)
            
        return detections

    def _maybe_log_stats(self) -> None:
        now = time.time()
        if now - self._last_stats_log < 30.0:
            return

        elapsed = now - self._last_stats_log
        actual_fps = self._frames_since_log / elapsed if elapsed > 0 else 0.0

        with self._linezones_lock:
            counts = {
                lid: {"in": z.in_count, "out": z.out_count}
                for lid, z in self.linezones.items()
            }

        logger.info(
            "stats | frames=%d actual_fps=%.1f stream_fps=%.1f "
            "latency=%.0f ms whip_recreations=%d frames_dropped=%d counts=%s",
            self._frame_count,
            actual_fps,
            self._current_fps,
            self._frame_latency_ms,
            self._whip_sink.recreations,
            self._whip_sink.frames_dropped,
            counts,
        )

        self._frames_since_log = 0
        self._last_stats_log = now

    # ── frame processing ──────────────────────────────────────────────────────

    def _snapshot_linezones(self) -> Dict[str, sv.LineZone]:
        with self._linezones_lock:
            return dict(self.linezones)

    # ── config sync ───────────────────────────────────────────────────────────

    def request_recording_start(self) -> None:
        logger.info("RECORDING STARTED")
        self._recording_state = True

    def request_recording_stop(self) -> None:
        logger.info("RECORDING STOPPED")
        self._recording_state = False
        self._frame_buffer.stop()

    def request_config_refresh(self) -> None:
        logger.info("config refresh requested")
        self.config_manager.update_all_from_config()
        self._rebuild_linezones(refresh=False)
        

    def request_line_reset(self) -> None:
        logger.info("line zone counter reset requested")
        self.config_manager.update_all_from_config()
        self._rebuild_linezones(refresh=True)

    def request_count_record(self) -> List[Dict[str, Any]]:
        count_records: List[Dict[str, Any]] = []
        with self._linezones_lock:
            for line_id, linezone in self.linezones.items():
                count_records.append({
                    "line_id": line_id,
                    "line_in_count": linezone.in_count,
                    "line_out_count": linezone.out_count,
                })
        self.request_line_reset()
        self._append_count_records(count_records)
        return count_records

    def _append_count_records(self, records: List[Dict[str, Any]]) -> None:
        data_dir = "data"
        os.makedirs(data_dir, exist_ok=True)
        path = os.path.join(data_dir, "counts.json")

        timestamp = datetime.now(timezone.utc).isoformat()
        stamped = [{"timestamp": timestamp, **r} for r in records]

        existing: List[Dict[str, Any]] = []
        if os.path.exists(path):
            try:
                with open(path) as f:
                    existing = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass

        existing.extend(stamped)
        with open(path, "w") as f:
            json.dump(existing, f, indent=2)

        logger.info("saved %d count records (%d total) to %s", len(stamped), len(existing), path)

    def _rebuild_linezones(self, refresh: bool = False) -> None:
        active = self.config_manager.sources.active_sources
        if not active:
            logger.warning("rebuild_linezones: no active sources, skipping")
            return
        source = active[0]

        res_w = source.resolution_width or 1080
        res_h = source.resolution_height or 1900
        line_dict = self.config_manager.lines.line_manager.to_dict()

        with self._linezones_lock:
            updated: Dict[str, sv.LineZone] = {}
            for line_id, line_cfg in line_dict.items():
                pt = line_cfg["point_list"]
                start = sv.Point(x=int(pt[0][0] * res_w), y=int(pt[0][1] * res_h))
                end = sv.Point(x=int(pt[1][0] * res_w), y=int(pt[1][1] * res_h))

                existing = self.linezones.get(line_id)
                if (
                    existing is not None
                    and existing.vector.start == start
                    and existing.vector.end == end
                    and refresh == False
                ):
                    updated[line_id] = existing
                    logger.debug("linezone %s unchanged", line_id)

                else:
                    updated[line_id] = sv.LineZone(
                        start=start, 
                        end=end,
                        triggering_anchors=[sv.Position.CENTER],
                        minimum_crossing_threshold=2
                    )
                    logger.info("linezone %s (re)created: %s → %s", line_id, start, end)
                    if (refresh):
                        logger.info("linezone count refreshed")

            removed = set(self.linezones) - set(updated)
            for lid in removed:
                logger.info("linezone %s removed", lid)

            self.linezones = updated

        logger.info(
            "linezones rebuilt: %d active %s",
            len(updated),
            list(updated.keys()),
        )
    

        






