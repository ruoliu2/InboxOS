from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

from app.integrations.google_workspace import GoogleAPIError, GoogleWorkspaceClient
from app.schemas.calendar import CalendarEvent, CreateCalendarEventRequest
from app.services.dependencies import (
    get_current_auth_session,
    get_google_workspace_client,
)
from app.storage.auth_store import AuthSessionRecord

router = APIRouter()


def require_google_access_token(session: AuthSessionRecord) -> str:
    if not session.access_token:
        raise HTTPException(
            status_code=401,
            detail="An active linked Google account is required.",
        )
    return session.access_token


@router.get("/events", response_model=list[CalendarEvent])
def list_calendar_events(
    time_min: datetime | None = Query(default=None),
    time_max: datetime | None = Query(default=None),
    session: AuthSessionRecord = Depends(get_current_auth_session),
    client: GoogleWorkspaceClient = Depends(get_google_workspace_client),
) -> list[CalendarEvent]:
    access_token = require_google_access_token(session)
    start = time_min or (datetime.now(UTC) - timedelta(days=14))
    end = time_max or (datetime.now(UTC) + timedelta(days=60))

    try:
        return client.list_calendar_events(
            access_token,
            time_min=start,
            time_max=end,
        )
    except GoogleAPIError as exc:
        raise HTTPException(status_code=exc.app_status_code, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/events", response_model=CalendarEvent)
def create_calendar_event(
    payload: CreateCalendarEventRequest,
    session: AuthSessionRecord = Depends(get_current_auth_session),
    client: GoogleWorkspaceClient = Depends(get_google_workspace_client),
) -> CalendarEvent:
    access_token = require_google_access_token(session)
    try:
        return client.create_calendar_event(access_token, payload)
    except GoogleAPIError as exc:
        raise HTTPException(status_code=exc.app_status_code, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.delete("/events/{event_id}", status_code=204)
def delete_calendar_event(
    event_id: str,
    session: AuthSessionRecord = Depends(get_current_auth_session),
    client: GoogleWorkspaceClient = Depends(get_google_workspace_client),
) -> None:
    access_token = require_google_access_token(session)
    try:
        client.delete_calendar_event(access_token, event_id)
    except GoogleAPIError as exc:
        raise HTTPException(status_code=exc.app_status_code, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
