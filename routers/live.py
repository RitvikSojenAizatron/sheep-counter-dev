import os

from fastapi import APIRouter

from services import api_service

router = APIRouter(prefix="/api/live", tags=["live"])

NGINX_BASE_URL = os.getenv("NGINX_BASE_URL", "http://vision.local")
MEDIAMTX_STREAM_NAME = os.getenv("MEDIAMTX_STREAM_NAME", "live")


@router.get("/stream")
def get_live_stream_config():
    whep_url = f"{NGINX_BASE_URL}/whep/{MEDIAMTX_STREAM_NAME}"
    return {"whepUrl": whep_url, "streamId": MEDIAMTX_STREAM_NAME}


@router.post("/recording/start")
def start_recording():
    api_service.start_recording()
    return {"ok": True}


@router.post("/recording/stop")
def stop_recording():
    api_service.stop_recording()
    return {"ok": True}
