from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from schemas.api import CameraCreate, CameraPatch
from services import api_service

SNAPSHOTS_DIR = Path("temp/snapshots")

router = APIRouter(prefix="/api/cameras", tags=["cameras"])


@router.get("")
def get_cameras():
    return api_service.get_cameras()


@router.post("")
def create_camera(payload: CameraCreate):
    return api_service.create_camera(payload)


@router.patch("/{camera_id}")
def patch_camera(camera_id: str, payload: CameraPatch):
    return api_service.patch_camera(camera_id, payload)


@router.delete("/{camera_id}")
def delete_camera(camera_id: str):
    return api_service.delete_camera(camera_id)


@router.get("/{camera_id}/snapshot")
def get_snapshot(camera_id: str):
    snapshot_path = SNAPSHOTS_DIR / f"{camera_id}.jpg"
    if not snapshot_path.exists():
        raise HTTPException(status_code=404, detail="Snapshot not available for this camera.")
    return FileResponse(snapshot_path, media_type="image/jpeg")
