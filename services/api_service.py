from __future__ import annotations

import logging
import os
from pathlib import Path

import requests as _requests
from fastapi import HTTPException

from schemas.api import CameraCreate, CameraPatch, LineCreate, LineDelete, LinePatch
from config_manager.ConfigManager import ConfigManager
from config_manager.ConfigUpdater import ConfigUpdateError, ConfigUpdater

logger = logging.getLogger(__name__)

CONFIG_PATH = "config/sources.json"
_PIPELINE_REFRESH_URL = os.getenv("PIPELINE_REFRESH_URL", "http://localhost:8001/refresh")
_PIPELINE_RECORD_URL = os.getenv("PIPELINE_RECORD_URL", "http://localhost:8001/record")
_PIPELINE_RECORDING_START_URL = os.getenv("PIPELINE_RECORDING_START_URL", "http://localhost:8001/recording/start")
_PIPELINE_RECORDING_STOP_URL = os.getenv("PIPELINE_RECORDING_STOP_URL", "http://localhost:8001/recording/stop")


def _notify_pipeline() -> None:
    try:
        _requests.post(_PIPELINE_REFRESH_URL, timeout=1)
    except Exception:
        pass


def record_counts() -> None:
    try:
        _requests.post(_PIPELINE_RECORD_URL, timeout=5)
    except Exception:
        pass


def start_recording() -> None:
    try:
        _requests.post(_PIPELINE_RECORDING_START_URL, timeout=2)
    except Exception:
        pass


def stop_recording() -> None:
    try:
        _requests.post(_PIPELINE_RECORDING_STOP_URL, timeout=2)
    except Exception:
        pass

config_manager = ConfigManager(sources_config_path=CONFIG_PATH)
config_updater = ConfigUpdater(config_path=CONFIG_PATH, config_manager=config_manager)


# --- Cameras ---

def get_cameras():
    config_manager.sources.load()
    sources = [
        *config_manager.sources.active_sources,
        *config_manager.sources.inactive_sources,
    ]
    return [_source_to_camera_dict(s) for s in sources]


def create_camera(payload: CameraCreate):
    from config_manager.Source import Source

    probe = Source.probe_source(ip_address=payload.ipAddress, source_type="RTSP")
    if not probe["connectable"]:
        raise HTTPException(
            status_code=400,
            detail=f"Could not connect to camera at {payload.ipAddress}.",
        )

    try:
        camera = config_updater.add_source(
            name=payload.name,
            active=payload.enabled if payload.enabled is not None else True,
            ip_address=payload.ipAddress,
            resolution_width=probe["width"],
            resolution_height=probe["height"],
        )
    except ConfigUpdateError as e:
        raise HTTPException(status_code=409, detail=str(e))

    Source.probe_source(
        ip_address=payload.ipAddress,
        source_type="RTSP",
        source_id=camera["id"],
    )
    _notify_pipeline()
    return camera


def patch_camera(camera_id: str, payload: CameraPatch, *, actor: str | None = None):
    from config_manager.Source import Source

    resolution_width = None
    resolution_height = None

    if payload.ipAddress is not None:
        probe = Source.probe_source(
            ip_address=payload.ipAddress,
            source_type="RTSP",
            source_id=camera_id,
        )
        if not probe["connectable"]:
            raise HTTPException(
                status_code=400,
                detail=f"Could not connect to camera at {payload.ipAddress}.",
            )
        resolution_width = probe["width"]
        resolution_height = probe["height"]

    try:
        config_updater.edit_source(
            id=camera_id,
            name=payload.name,
            ip_address=payload.ipAddress,
            active=payload.enabled,
            resolution_width=resolution_width,
            resolution_height=resolution_height,
        )
    except ConfigUpdateError as e:
        raise HTTPException(status_code=404, detail=str(e))

    config_manager.sources.load()
    _notify_pipeline()
    source = _find_source(camera_id)
    return _source_to_camera_dict(source) if source else {"id": camera_id}


def delete_camera(camera_id: str):
    try:
        config_updater.delete_source(camera_id)
    except ConfigUpdateError as e:
        raise HTTPException(status_code=404, detail=str(e))

    Path("temp/snapshots", f"{camera_id}.jpg").unlink(missing_ok=True)
    _notify_pipeline()
    return {"id": camera_id, "deleted": True}


# --- Lines ---

def get_lines():
    config_manager.sources.load()
    lines = []
    for source in [
        *config_manager.sources.active_sources,
        *config_manager.sources.inactive_sources,
    ]:
        for line in source.lineManager.line_list:
            lines.append(_line_to_dict(line, source.id))
    return lines


def create_line(payload: LineCreate, *, actor: str | None = None):
    crossing_direction = (
        [[p["x"], p["y"]] for p in payload.crossing_vector]
        if payload.crossing_vector
        else None
    )
    mutation = {
        "cameraId": payload.cameraId,
        "name": payload.name,
        "points": payload.endpoints,
        "crossing_direction": crossing_direction,
        # endpoints are already normalized [0-1] fractions from the frontend;
        # passing 0 prevents ConfigUpdater from dividing by camera resolution again.
        "resolution_width": 0,
        "resolution_height": 0,
    }
    try:
        config_updater.add_line(mutation)
    except ConfigUpdateError as e:
        raise HTTPException(status_code=409, detail=str(e))

    config_manager.sources.load()
    _notify_pipeline()
    return {"name": payload.name, "cameraId": payload.cameraId}


def patch_line(line_id: str, payload: LinePatch, *, actor: str | None = None):
    crossing_direction = (
        [[p["x"], p["y"]] for p in payload.crossing_vector]
        if payload.crossing_vector
        else None
    )
    mutation = {
        "name": payload.name,
        "points": payload.endpoints,
        "crossing_direction": crossing_direction,
        "resolution_width": 0,
        "resolution_height": 0,
    }
    try:
        config_updater.edit_line(payload.cameraId, line_id, mutation)
    except ConfigUpdateError as e:
        status = 404 if "not found" in str(e).lower() else 409
        raise HTTPException(status_code=status, detail=str(e))

    config_manager.sources.load()
    _notify_pipeline()
    return {"id": line_id, "name": payload.name, "cameraId": payload.cameraId}


def delete_line(line_id: str, *, actor: str | None = None):
    camera_id = _find_line_camera(line_id)
    if camera_id is None:
        raise HTTPException(status_code=404, detail=f"Line '{line_id}' not found.")

    try:
        config_updater.delete_line(camera_id, line_id)
    except ConfigUpdateError as e:
        raise HTTPException(status_code=404, detail=str(e))

    config_manager.sources.load()
    _notify_pipeline()
    return {"id": line_id, "deleted": True}


# --- Helpers ---

def _find_line_camera(line_id: str) -> "str | None":
    config_manager.sources.load()
    for source in [*config_manager.sources.active_sources, *config_manager.sources.inactive_sources]:
        for line in source.lineManager.line_list:
            if line.id == line_id:
                return source.id
    return None


def _find_source(source_id: str):
    for source in [
        *config_manager.sources.active_sources,
        *config_manager.sources.inactive_sources,
    ]:
        if source.id == source_id:
            return source
    return None


def _source_to_camera_dict(source) -> dict:
    return {
        "id": source.id,
        "name": source.name,
        "tileIndex": getattr(source, "window_id", 0),
        "enabled": source.active,
        "ipAddress": source.ip_address,
        "lastFrameTimestamp": source.captured_at,
        "effectiveFps": 0,
        "online": True,
    }


def _line_to_dict(line, camera_id: str) -> dict:
    endpoints = [{"x": p[0], "y": p[1]} for p in line.point_list]
    crossing_vector = (
        [{"x": p[0], "y": p[1]} for p in line.crossing_direction]
        if line.crossing_direction
        else []
    )
    return {
        "id": line.id,
        "name": line.name,
        "cameraId": camera_id,
        "endpoints": endpoints,
        "crossing_vector": crossing_vector,
    }
