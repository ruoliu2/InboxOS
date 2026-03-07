from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from urllib.parse import quote

from app.core.config import Settings
from app.integrations.google_workspace import GoogleWorkspaceClient
from app.schemas.auth import AuthStartResponse
from app.storage.store import AuthSessionRecord, InMemoryStore, OAuthStateRecord


@dataclass
class AuthCallbackResult:
    redirect_url: str
    session: AuthSessionRecord


class AuthService:
    def __init__(
        self,
        store: InMemoryStore,
        google_client: GoogleWorkspaceClient,
        settings: Settings,
    ) -> None:
        self.store = store
        self.google_client = google_client
        self.settings = settings

    def start_google_auth(self, redirect_to: str | None = None) -> AuthStartResponse:
        state = token_urlsafe(24)
        safe_redirect = self._normalize_redirect_to(redirect_to)
        self.store.save_oauth_state(
            OAuthStateRecord(
                state=state,
                redirect_to=safe_redirect,
                created_at=datetime.now(UTC),
            )
        )
        return AuthStartResponse(
            provider="google",
            authorization_url=self.google_client.build_authorization_url(state),
            state=state,
        )

    def handle_google_callback(
        self,
        *,
        code: str | None,
        state: str | None,
    ) -> AuthCallbackResult:
        if not code:
            raise ValueError("Missing Google authorization code.")
        if not state:
            raise ValueError("Missing Google OAuth state.")

        pending_state = self.store.pop_oauth_state(state)
        if pending_state is None:
            raise ValueError("Google OAuth state is invalid or expired.")

        tokens = self.google_client.exchange_code_for_tokens(code)
        profile = self.google_client.get_user_profile(tokens.access_token)
        now = datetime.now(UTC)
        session = AuthSessionRecord(
            session_id=token_urlsafe(32),
            provider="google",
            account_email=profile.email,
            account_name=profile.name,
            account_picture=profile.picture,
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            scope=tokens.scope,
            expires_at=tokens.expires_at,
            created_at=now,
            updated_at=now,
        )
        self.store.upsert_session(session)

        return AuthCallbackResult(
            redirect_url=self._absolute_redirect(pending_state.redirect_to),
            session=session,
        )

    def get_session(self, session_id: str | None) -> AuthSessionRecord | None:
        if not session_id:
            return None

        session = self.store.get_session(session_id)
        if session is None:
            return None

        if self._is_expired(session) and session.refresh_token:
            try:
                refreshed = self.google_client.refresh_access_token(
                    session.refresh_token
                )
            except RuntimeError:
                self.store.delete_session(session.session_id)
                return None

            session.access_token = refreshed.access_token
            session.refresh_token = refreshed.refresh_token or session.refresh_token
            session.scope = refreshed.scope or session.scope
            session.expires_at = refreshed.expires_at
            session.updated_at = datetime.now(UTC)
            self.store.upsert_session(session)
            return session

        if self._is_expired(session) and not session.refresh_token:
            self.store.delete_session(session.session_id)
            return None

        return session

    def clear_session(self, session_id: str | None) -> None:
        if session_id:
            self.store.delete_session(session_id)

    def error_redirect(self, message: str) -> str:
        return self._absolute_redirect(f"/auth?error={quote(message)}")

    def _absolute_redirect(self, path: str) -> str:
        return f"{self.settings.web_base_url.rstrip('/')}{path}"

    def _normalize_redirect_to(self, value: str | None) -> str:
        if not value or not value.startswith("/") or value.startswith("//"):
            return "/mail"
        return value

    def _is_expired(self, session: AuthSessionRecord) -> bool:
        if session.expires_at is None:
            return False
        return session.expires_at <= datetime.now(UTC) + timedelta(seconds=30)
