from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from services.ws_manager import ws_manager

router = APIRouter(tags=["ws"])


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws_manager.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(ws)


@router.post("/api/internal/pipeline-metric")
async def post_pipeline_metric(payload: dict):
    await ws_manager.broadcast_pipeline_metric(payload)
    return {"ok": True}
