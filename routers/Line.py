from fastapi import APIRouter

from schemas.api import LineCreate, LinePatch
from services import api_service

router = APIRouter(prefix="/api/lines", tags=["lines"])


@router.get("")
def get_lines():
    return api_service.get_lines()


@router.post("")
def create_line(payload: LineCreate):
    return api_service.create_line(payload)


@router.patch("/{line_id}")
def patch_line(line_id: str, payload: LinePatch):
    return api_service.patch_line(line_id, payload)


@router.delete("/{line_id}")
def delete_line(line_id: str):
    return api_service.delete_line(line_id)
