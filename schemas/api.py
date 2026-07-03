from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class ModelPatch(BaseModel):
    conf_threshold: float | None = None
    model_type: str 
    buffer_frame_size: int

class RefreshRequest(BaseModel):
    refreshToken: str


class CameraCreate(BaseModel):
    name: str
    enabled: Optional[bool] = None
    ipAddress: str
    password: Optional[str] = None
    lastFrameTimestamp: Optional[str] = None
    effectiveFps: Optional[float] = None
    online: Optional[bool] = None


class CameraPatch(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    tileIndex: Optional[int] = None
    enabled: Optional[bool] = None
    ipAddress: Optional[str] = None
    password: Optional[str] = None
    lastFrameTimestamp: Optional[str] = None
    effectiveFps: Optional[float] = None
    online: Optional[bool] = None


class LineCreate(BaseModel):
    name: str
    cameraId: str
    endpoints: List[Dict[str, float]]
    crossing_vector: Optional[List[Dict[str, float]]] = None


class LinePatch(BaseModel):
    name: str
    cameraId: str
    endpoints: List[Dict[str, float]]
    crossing_vector: Optional[List[Dict[str, float]]] = None


class LineDelete(BaseModel):
    name: str
    cameraID: str

class CommandRequest(BaseModel):
    action: str


class HostnameCheckRequest(BaseModel):
    name: str
