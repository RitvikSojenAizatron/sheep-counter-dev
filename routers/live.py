import os

from fastapi import APIRouter

from services import api_service

router = APIRouter(prefix="/api/live", tags=["live"])

MEDIAMTX_HOST = os.getenv("MEDIAMTX_HOST", "localhost")
MEDIAMTX_WHEP_PORT = os.getenv("MEDIAMTX_WHEP_PORT", "8889")
MEDIAMTX_STREAM_NAME = os.getenv("MEDIAMTX_STREAM_NAME", "live")


@router.get("/stream")
def get_live_stream_config():
    whep_url = f"http://{MEDIAMTX_HOST}:{MEDIAMTX_WHEP_PORT}/{MEDIAMTX_STREAM_NAME}/whep"
    return {"whepUrl": whep_url, "streamId": MEDIAMTX_STREAM_NAME}


@router.post("/recording/start")
def start_recording():
    api_service.start_recording()
    return {"ok": True}


@router.post("/recording/stop")
def stop_recording():
    api_service.stop_recording()
    return {"ok": True}
