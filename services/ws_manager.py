import json
from typing import Any

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self._connections:
            self._connections.remove(ws)

    async def broadcast(self, message: dict[str, Any]) -> None:
        data = json.dumps(message)
        dead: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def broadcast_pipeline_metric(self, payload: dict[str, Any]) -> None:
        await self.broadcast({"type": "pipeline_metric", **payload})

    async def broadcast_camera_metric(self, payload: dict[str, Any]) -> None:
        await self.broadcast({"type": "camera_metric", **payload})

    async def broadcast_source_status(self, payload: dict[str, Any]) -> None:
        await self.broadcast({"type": "source_status", **payload})


ws_manager = ConnectionManager()
