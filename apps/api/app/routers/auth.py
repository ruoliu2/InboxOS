from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from app.core.config import get_settings
from app.schemas.auth import (
    AuthSessionResponse,
    AuthStartResponse,
    AuthUserResponse,
    LinkedAccountResponse,
)
from app.services.auth_service import AuthService
from app.services.dependencies import get_auth_service
from app.storage.auth_store import AuthSessionRecord

router = APIRouter()


def build_auth_session_response(
    service: AuthService,
    session: AuthSessionRecord | None,
) -> AuthSessionResponse:
    if session is None:
        return AuthSessionResponse(authenticated=False)

    user = service.get_user(session.user_id)
    linked_accounts = [
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
    return AuthSessionResponse(
        authenticated=True,
        user=(
            AuthUserResponse(
                id=user.id,
                primary_email=user.primary_email,
                display_name=user.display_name,
                avatar_url=user.avatar_url,
            )
            if user is not None
            else None
        ),
        active_account_id=session.active_linked_account_id,
        linked_accounts=linked_accounts,
        provider=session.provider,
        account_email=session.account_email,
        account_name=session.account_name,
        account_picture=session.account_picture,
    )


@router.get("/google/start", response_model=AuthStartResponse)
def start_google_auth(
    request: Request,
    redirect_to: str | None = Query(default=None),
    service: AuthService = Depends(get_auth_service),
) -> AuthStartResponse:
    try:
        current_session = service.get_session(
            request.cookies.get(get_settings().session_cookie_name)
        )
        return service.start_google_auth(
            redirect_to=redirect_to,
            current_session=current_session,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/google/callback")
def google_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    service: AuthService = Depends(get_auth_service),
) -> Response:
    try:
        result = service.handle_google_callback(code=code, state=state)
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


@router.get("/session", response_model=AuthSessionResponse)
def auth_session(
    request: Request,
    response: Response,
    service: AuthService = Depends(get_auth_service),
) -> AuthSessionResponse:
    settings = get_settings()
    session = service.get_session(request.cookies.get(settings.session_cookie_name))
    if session is None:
        if request.cookies.get(settings.session_cookie_name):
            service.clear_session_cookie(response)
        return AuthSessionResponse(authenticated=False)

    service.set_session_cookie(response, session)
    return build_auth_session_response(service, session)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    service: AuthService = Depends(get_auth_service),
) -> Response:
    session_id = request.cookies.get(get_settings().session_cookie_name)
    service.clear_session(session_id)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    service.clear_session_cookie(response)
    return response
