from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

from app.integrations.google_workspace import GoogleAPIError, GoogleWorkspaceClient
from app.schemas.calendar import CalendarEvent, CreateCalendarEventRequest
from app.services.auth_service import AuthService, LinkedAccountAccess
from app.services.dependencies import (
    get_auth_service,
    get_current_auth_session,
    get_google_workspace_client,
)
from app.storage.auth_store import AuthSessionRecord

router = APIRouter()

ALL_SCOPE = "all"


def with_account_metadata(
    event: CalendarEvent,
    access: LinkedAccountAccess,
) -> CalendarEvent:
    payload = event.model_dump()
    payload["linked_account_id"] = access.account.id
    payload["account_email"] = access.account.provider_account_ref
    payload["account_name"] = access.account.display_name
    return CalendarEvent(**payload)


def resolve_calendar_accounts_for_scope(
    scope: str,
    session: AuthSessionRecord,
    service: AuthService,
) -> list[LinkedAccountAccess]:
    if not session.user_id:
        raise HTTPException(status_code=401, detail="Authentication required.")

    normalized_scope = (scope or ALL_SCOPE).strip() or ALL_SCOPE
    if normalized_scope == ALL_SCOPE:
        accounts = service.list_active_account_access(
            session.user_id,
            provider="google_gmail",
        )
        if not accounts:
            raise HTTPException(
                status_code=404,
                detail="No active linked Google accounts are available.",
            )
        return accounts

    access = service.get_linked_account_access(session.user_id, normalized_scope)
    if access is None or access.account.provider != "google_gmail":
        raise HTTPException(status_code=404, detail="Linked Google account not found.")
    return [access]


def resolve_calendar_write_account(
    session: AuthSessionRecord,
    service: AuthService,
    linked_account_id: str | None,
) -> LinkedAccountAccess:
    if not session.user_id:
        raise HTTPException(status_code=401, detail="Authentication required.")

    target_id = linked_account_id or session.active_linked_account_id
    if not target_id:
        raise HTTPException(
            status_code=422,
            detail="A linked Google account is required for calendar writes.",
        )

    access = service.get_linked_account_access(session.user_id, target_id)
    if access is None or access.account.provider != "google_gmail":
        raise HTTPException(status_code=404, detail="Linked Google account not found.")
    return access


@router.get("/events", response_model=list[CalendarEvent])
def list_calendar_events(
    time_min: datetime | None = Query(default=None),
    time_max: datetime | None = Query(default=None),
    scope: str = Query(default=ALL_SCOPE),
    session: AuthSessionRecord = Depends(get_current_auth_session),
    service: AuthService = Depends(get_auth_service),
    client: GoogleWorkspaceClient = Depends(get_google_workspace_client),
) -> list[CalendarEvent]:
    start = time_min or (datetime.now(UTC) - timedelta(days=14))
    end = time_max or (datetime.now(UTC) + timedelta(days=60))
    accounts = resolve_calendar_accounts_for_scope(scope, session, service)

    merged_events: list[CalendarEvent] = []
    for access in accounts:
        try:
            events = client.list_calendar_events(
                access.credential.access_token,
                time_min=start,
                time_max=end,
            )
        except GoogleAPIError as exc:
            raise HTTPException(
                status_code=exc.app_status_code, detail=str(exc)
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        merged_events.extend(with_account_metadata(event, access) for event in events)

    merged_events.sort(key=lambda event: event.starts_at)
    return merged_events


@router.post("/events", response_model=CalendarEvent)
def create_calendar_event(
    payload: CreateCalendarEventRequest,
    session: AuthSessionRecord = Depends(get_current_auth_session),
    service: AuthService = Depends(get_auth_service),
    client: GoogleWorkspaceClient = Depends(get_google_workspace_client),
) -> CalendarEvent:
    access = resolve_calendar_write_account(session, service, payload.linked_account_id)

    try:
        created = client.create_calendar_event(access.credential.access_token, payload)
    except GoogleAPIError as exc:
        raise HTTPException(status_code=exc.app_status_code, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return with_account_metadata(created, access)


@router.delete("/events/{event_id}", status_code=204)
def delete_calendar_event(
    event_id: str,
    linked_account_id: str | None = Query(default=None),
    session: AuthSessionRecord = Depends(get_current_auth_session),
    service: AuthService = Depends(get_auth_service),
    client: GoogleWorkspaceClient = Depends(get_google_workspace_client),
) -> None:
    access = resolve_calendar_write_account(session, service, linked_account_id)

    try:
        client.delete_calendar_event(access.credential.access_token, event_id)
    except GoogleAPIError as exc:
        raise HTTPException(status_code=exc.app_status_code, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
