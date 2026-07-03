from fastapi import APIRouter
from services import api_service

router = APIRouter(prefix="/api/counts", tags=["counts"])


@router.post("/record")
def record_counts():
    api_service.record_counts()
    return {"ok": True}
