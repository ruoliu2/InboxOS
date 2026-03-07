from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

from app.integrations.google_workspace import GoogleAPIError, GoogleWorkspaceClient
from app.schemas.calendar import CalendarEvent
from app.services.dependencies import (
    get_current_auth_session,
    get_google_workspace_client,
)
from app.storage.auth_store import AuthSessionRecord

router = APIRouter()


@router.get("/events", response_model=list[CalendarEvent])
def list_calendar_events(
    time_min: datetime | None = Query(default=None),
    time_max: datetime | None = Query(default=None),
    session: AuthSessionRecord = Depends(get_current_auth_session),
    client: GoogleWorkspaceClient = Depends(get_google_workspace_client),
) -> list[CalendarEvent]:
    start = time_min or (datetime.now(UTC) - timedelta(days=14))
    end = time_max or (datetime.now(UTC) + timedelta(days=60))

    try:
        return client.list_calendar_events(
            session.access_token,
            time_min=start,
            time_max=end,
        )
    except GoogleAPIError as exc:
        raise HTTPException(status_code=exc.app_status_code, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
