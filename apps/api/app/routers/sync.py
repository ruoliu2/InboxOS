from fastapi import APIRouter, Depends

from app.schemas.sync import SyncStartRequest, SyncStartResponse, SyncStatusResponse
from app.services.dependencies import get_sync_service
from app.services.sync_service import SyncService

router = APIRouter()


@router.post("/start", response_model=SyncStartResponse)
def start_sync(
    payload: SyncStartRequest,
    service: SyncService = Depends(get_sync_service),
) -> SyncStartResponse:
    result = service.start_sync(payload)
    return SyncStartResponse(**result, started_at=result["updated_at"])


@router.get("/status", response_model=SyncStatusResponse)
def sync_status(service: SyncService = Depends(get_sync_service)) -> SyncStatusResponse:
    return SyncStatusResponse(**service.get_status())
