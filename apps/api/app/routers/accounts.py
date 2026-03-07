from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from app.core.config import get_settings
from app.routers.auth import build_auth_session_response
from app.schemas.auth import (
    AuthSessionResponse,
    AuthStartResponse,
    LinkedAccountResponse,
)
from app.services.auth_service import AuthService
from app.services.dependencies import get_auth_service, get_current_auth_session
from app.storage.auth_store import AuthSessionRecord

router = APIRouter()


@router.get("", response_model=list[LinkedAccountResponse])
def list_accounts(
    session: AuthSessionRecord = Depends(get_current_auth_session),
    service: AuthService = Depends(get_auth_service),
) -> list[LinkedAccountResponse]:
    return [
        LinkedAccountResponse(
            id=account.id,
            provider=account.provider,
            provider_account_id=account.provider_account_id,
            provider_account_ref=account.provider_account_ref,
            display_name=account.display_name,
            avatar_url=account.avatar_url,
            status=account.status,
            capabilities=account.capabilities,
            last_synced_at=account.last_synced_at,
        )
        for account in service.list_linked_accounts(session.user_id)
    ]


@router.post("/{provider}/connect/start", response_model=AuthStartResponse)
def start_account_connect(
    provider: str,
    request: Request,
    redirect_to: str | None = Query(default=None),
    service: AuthService = Depends(get_auth_service),
) -> AuthStartResponse:
    current_session = service.get_session(
        request.cookies.get(get_settings().session_cookie_name)
    )
    try:
        return service.start_provider_auth(
            provider,
            redirect_to=redirect_to,
            current_session=current_session,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/{provider}/callback")
def provider_callback(
    provider: str,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    service: AuthService = Depends(get_auth_service),
) -> Response:
    try:
        result = service.handle_provider_callback(provider, code=code, state=state)
    except ValueError as exc:
        return RedirectResponse(
            url=service.error_redirect(str(exc)),
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except RuntimeError as exc:
        return RedirectResponse(
            url=service.error_redirect(str(exc)),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    response = RedirectResponse(
        url=result.redirect_url,
        status_code=status.HTTP_303_SEE_OTHER,
    )
    service.set_session_cookie(response, result.session)
    return response


@router.post("/{account_id}/disconnect", status_code=status.HTTP_204_NO_CONTENT)
def disconnect_account(
    account_id: str,
    session: AuthSessionRecord = Depends(get_current_auth_session),
    service: AuthService = Depends(get_auth_service),
) -> Response:
    service.disconnect_account(session.user_id, account_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{account_id}/activate", response_model=AuthSessionResponse)
def activate_account(
    account_id: str,
    response: Response,
    session: AuthSessionRecord = Depends(get_current_auth_session),
    service: AuthService = Depends(get_auth_service),
) -> AuthSessionResponse:
    try:
        next_session = service.activate_account(
            session.session_id, session.user_id, account_id
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    service.set_session_cookie(response, next_session)
    return build_auth_session_response(service, next_session)
