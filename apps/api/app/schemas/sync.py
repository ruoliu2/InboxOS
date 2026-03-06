from datetime import datetime

from pydantic import BaseModel

from app.schemas.common import SyncStatus


class SyncStartRequest(BaseModel):
    account_email: str | None = None
    force: bool = False


class SyncStartResponse(BaseModel):
    sync_id: str
    status: SyncStatus
    imported_threads: int
    started_at: datetime


class SyncStatusResponse(BaseModel):
    sync_id: str | None = None
    status: SyncStatus
    imported_threads: int
    updated_at: datetime
    last_error: str | None = None
