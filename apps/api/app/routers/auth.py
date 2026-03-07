from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from app.core.config import get_settings
from app.schemas.auth import AuthSessionResponse, AuthStartResponse
from app.services.auth_service import AuthService
from app.services.dependencies import get_auth_service

router = APIRouter()


@router.get("/google/start", response_model=AuthStartResponse)
def start_google_auth(
    redirect_to: str | None = Query(default=None),
    service: AuthService = Depends(get_auth_service),
) -> AuthStartResponse:
    try:
        return service.start_google_auth(redirect_to=redirect_to)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/google/callback")
def google_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    service: AuthService = Depends(get_auth_service),
) -> Response:
    settings = get_settings()
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
    response.set_cookie(
        key=settings.session_cookie_name,
        value=result.session.session_id,
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
        path="/",
    )
    return response


@router.get("/session", response_model=AuthSessionResponse)
def auth_session(
    request: Request,
    service: AuthService = Depends(get_auth_service),
) -> AuthSessionResponse:
    settings = get_settings()
    session = service.get_session(request.cookies.get(settings.session_cookie_name))
    if session is None:
        return AuthSessionResponse(authenticated=False)

    return AuthSessionResponse(
        authenticated=True,
        provider=session.provider,
        account_email=session.account_email,
        account_name=session.account_name,
        account_picture=session.account_picture,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    service: AuthService = Depends(get_auth_service),
) -> Response:
    settings = get_settings()
    session_id = request.cookies.get(settings.session_cookie_name)
    service.clear_session(session_id)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
    )
    return response
