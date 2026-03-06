from secrets import token_urlsafe

from app.schemas.auth import AuthCallbackResponse, AuthStartResponse


class AuthService:
    def start_google_auth(self) -> AuthStartResponse:
        state = token_urlsafe(18)
        url = (
            "https://accounts.google.com/o/oauth2/v2/auth"
            "?client_id=demo-client"
            "&response_type=code"
            "&scope=email%20profile"
            "&redirect_uri=http://localhost:8000/auth/google/callback"
            f"&state={state}"
        )
        return AuthStartResponse(provider="google", authorization_url=url, state=state)

    def handle_google_callback(self, code: str | None = None) -> AuthCallbackResponse:
        if not code:
            return AuthCallbackResponse(
                provider="google",
                connected=False,
                account_email="",
                message="Missing code query parameter.",
            )

        return AuthCallbackResponse(
            provider="google",
            connected=True,
            account_email="demo.user@gmail.com",
            message="OAuth callback accepted in MVP mode.",
        )
