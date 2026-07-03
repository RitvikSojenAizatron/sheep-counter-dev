from fastapi import APIRouter, Depends

from src.app.auth.dependencies import get_current_user, require_admin
from src.app.schemas.api import ModelPatch
from src.app.services import api_service

router = APIRouter(
    prefix="/api/model",
    tags=["model"]
)


@router.get("")
def get_model():
    return api_service.get_model()


@router.patch("")
def patch_model(payload: ModelPatch):
    return api_service.patch_model(payload, actor=current_user["name"])