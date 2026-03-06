from fastapi import APIRouter, Depends, Query

from app.schemas.auth import AuthCallbackResponse, AuthStartResponse
from app.services.auth_service import AuthService
from app.services.dependencies import get_auth_service

router = APIRouter()


@router.get("/google/start", response_model=AuthStartResponse)
def start_google_auth(
    service: AuthService = Depends(get_auth_service),
) -> AuthStartResponse:
    return service.start_google_auth()


@router.get("/google/callback", response_model=AuthCallbackResponse)
def google_callback(
    code: str | None = Query(default=None),
    service: AuthService = Depends(get_auth_service),
) -> AuthCallbackResponse:
    return service.handle_google_callback(code)
