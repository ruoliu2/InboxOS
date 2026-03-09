from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from urllib.parse import quote

from fastapi import Response

from app.core.config import Settings
from app.integrations.google_workspace import GoogleWorkspaceClient
from app.schemas.auth import AuthStartResponse
from app.storage.auth_store import (
    AppUserRecord,
    AuthSessionRecord,
    AuthStore,
    LinkedAccountRecord,
    OAuthFlowRecord,
    ProviderCredentialRecord,
    canonical_provider,
)


@dataclass
class AuthCallbackResult:
    redirect_url: str
    session: AuthSessionRecord


@dataclass
class LinkedAccountAccess:
    account: LinkedAccountRecord
    credential: ProviderCredentialRecord


class AuthService:
    def __init__(
        self,
        store: AuthStore,
        google_client: GoogleWorkspaceClient,
        settings: Settings,
    ) -> None:
        self.store = store
        self.google_client = google_client
        self.settings = settings

    def start_google_auth(
        self,
        redirect_to: str | None = None,
        current_session: AuthSessionRecord | None = None,
    ) -> AuthStartResponse:
        return self.start_provider_auth(
            "google_gmail",
            redirect_to=redirect_to,
            current_session=current_session,
        )

    def start_provider_auth(
        self,
        provider: str,
        *,
        redirect_to: str | None = None,
        current_session: AuthSessionRecord | None = None,
    ) -> AuthStartResponse:
        canonical = self._supported_provider(provider)
        if canonical != "google_gmail":
            raise RuntimeError(f"Provider {canonical} is not implemented yet.")
        state = token_urlsafe(24)
        safe_redirect = self._normalize_redirect_to(redirect_to)
        now = datetime.now(UTC)
        self.store.save_oauth_flow(
            OAuthFlowRecord(
                state=state,
                provider=canonical,
                intent="link_account" if current_session is not None else "sign_in",
                user_id=(
                    current_session.user_id if current_session is not None else None
                ),
                redirect_to=safe_redirect,
                pkce_verifier=None,
                requested_scopes=[],
                expires_at=now
                + timedelta(seconds=self.settings.oauth_state_ttl_seconds),
                consumed_at=None,
                created_at=now,
                updated_at=now,
            )
        )
        return AuthStartResponse(
            provider=canonical,
            authorization_url=self.google_client.build_authorization_url(state),
            state=state,
        )

    def handle_google_callback(
        self,
        *,
        code: str | None,
        state: str | None,
    ) -> AuthCallbackResult:
        return self.handle_provider_callback(
            "google_gmail",
            code=code,
            state=state,
        )

    def handle_provider_callback(
        self,
        provider: str,
        *,
        code: str | None,
        state: str | None,
    ) -> AuthCallbackResult:
        canonical = self._supported_provider(provider)
        if not code:
            raise ValueError("Missing Google authorization code.")
        if not state:
            raise ValueError("Missing Google OAuth state.")

        pending_flow = self.store.consume_oauth_flow(state)
        if pending_flow is None:
            raise ValueError("Google OAuth state is invalid or expired.")
        if pending_flow.provider != canonical:
            raise ValueError("OAuth flow provider did not match the callback route.")

        tokens = self.google_client.exchange_code_for_tokens(code)
        profile = self.google_client.get_user_profile(tokens.access_token)
        now = datetime.now(UTC)

        linked_account = self.store.find_linked_account(
            canonical, profile.email.lower()
        )
        user = None
        if pending_flow.user_id:
            user = self.store.get_user(pending_flow.user_id)
        if user is None and linked_account is not None:
            user = self.store.get_user(linked_account.user_id)
        if user is None:
            user = self.store.find_user_by_primary_email(profile.email)

        user = self.store.upsert_user(
            AppUserRecord(
                id=user.id if user is not None else token_urlsafe(12),
                primary_email=profile.email,
                display_name=profile.name,
                avatar_url=profile.picture,
                created_at=user.created_at if user is not None else now,
                updated_at=now,
            )
        )
        account = self.store.upsert_linked_account(
            LinkedAccountRecord(
                id=(
                    linked_account.id
                    if linked_account is not None
                    else token_urlsafe(12)
                ),
                user_id=user.id,
                provider=canonical,
                provider_account_id=profile.email.lower(),
                provider_account_ref=profile.email,
                display_name=profile.name,
                avatar_url=profile.picture,
                status="active",
                capabilities=["mail", "calendar"],
                metadata={},
                last_synced_at=now,
                created_at=(
                    linked_account.created_at if linked_account is not None else now
                ),
                updated_at=now,
            )
        )
        self.store.upsert_provider_credential(
            ProviderCredentialRecord(
                linked_account_id=account.id,
                access_token=tokens.access_token,
                refresh_token=tokens.refresh_token,
                scope=tokens.scope,
                expires_at=tokens.expires_at,
                created_at=now,
                updated_at=now,
            )
        )

        session = self.store.create_or_update_session(
            AuthSessionRecord(
                session_id=token_urlsafe(32),
                user_id=user.id,
                active_linked_account_id=account.id,
                provider=account.provider,
                account_email=account.provider_account_ref,
                account_name=account.display_name,
                account_picture=account.avatar_url,
                access_token=tokens.access_token,
                refresh_token=tokens.refresh_token,
                scope=tokens.scope,
                expires_at=tokens.expires_at,
                session_expires_at=now + self._session_ttl(),
                created_at=now,
                updated_at=now,
            )
        )

        return AuthCallbackResult(
            redirect_url=self._absolute_redirect(pending_flow.redirect_to),
            session=session,
        )

    def get_session(self, session_id: str | None) -> AuthSessionRecord | None:
        if not session_id:
            return None

        session = self.store.get_session(session_id)
        if session is None:
            return None

        now = datetime.now(UTC)
        if self._is_session_expired(session, now):
            self.store.delete_session(session.session_id)
            return None

        if not session.active_linked_account_id or not session.user_id:
            self.store.delete_session(session.session_id)
            return None

        if self._is_google_provider(session.provider):
            token_refreshed = False
            if self._is_google_token_expired(session, now) and session.refresh_token:
                try:
                    refreshed = self.google_client.refresh_access_token(
                        session.refresh_token
                    )
                except RuntimeError:
                    self.store.delete_session(session.session_id)
                    return None

                now = datetime.now(UTC)
                session.access_token = refreshed.access_token
                session.refresh_token = refreshed.refresh_token or session.refresh_token
                session.scope = refreshed.scope or session.scope
                session.expires_at = refreshed.expires_at
                token_refreshed = True
            elif (
                self._is_google_token_expired(session, now)
                and not session.refresh_token
            ):
                self.store.delete_session(session.session_id)
                return None
        else:
            token_refreshed = False

        session.session_expires_at = now + self._session_ttl()
        session.updated_at = now
        if token_refreshed:
            self.store.upsert_session(session)
        else:
            self.store.update_session_expiry(
                session.session_id,
                session.session_expires_at,
                session.updated_at,
            )
        return self.store.get_session(session.session_id)

    def clear_session(self, session_id: str | None) -> None:
        if session_id:
            self.store.delete_session(session_id)

    def list_linked_accounts(self, user_id: str) -> list[LinkedAccountRecord]:
        return self.store.list_linked_accounts(user_id)

    def get_linked_account_access(
        self,
        user_id: str,
        linked_account_id: str,
    ) -> LinkedAccountAccess | None:
        account = self.store.get_linked_account(user_id, linked_account_id)
        if account is None or account.status != "active":
            return None
        return self._linked_account_access(account)

    def list_active_account_access(
        self,
        user_id: str,
        *,
        provider: str | None = None,
    ) -> list[LinkedAccountAccess]:
        accounts = []
        for account in self.store.list_linked_accounts(user_id):
            if account.status != "active":
                continue
            if provider and canonical_provider(account.provider) != canonical_provider(
                provider
            ):
                continue
            access = self._linked_account_access(account)
            if access is not None:
                accounts.append(access)
        return accounts

    def get_user(self, user_id: str | None) -> AppUserRecord | None:
        if not user_id:
            return None
        return self.store.get_user(user_id)

    def activate_account(
        self,
        session_id: str,
        user_id: str,
        linked_account_id: str,
    ) -> AuthSessionRecord:
        account = self.store.get_linked_account(user_id, linked_account_id)
        if account is None:
            raise KeyError(f"account {linked_account_id} not found")
        if account.status != "active":
            raise ValueError(f"account {linked_account_id} is not active")
        self.store.set_active_account(session_id, user_id, linked_account_id)
        session = self.store.get_session(session_id)
        if session is None:
            raise KeyError(f"session {session_id} not found")
        return session

    def disconnect_account(self, user_id: str, linked_account_id: str) -> None:
        remaining_accounts = [
            account
            for account in self.store.list_linked_accounts(user_id)
            if account.id != linked_account_id and account.status == "active"
        ]
        self.store.disconnect_account(user_id, linked_account_id)
        if remaining_accounts:
            replacement = remaining_accounts[0]
            for session in self.store.list_sessions_for_user(user_id):
                if session.active_linked_account_id == linked_account_id:
                    self.store.set_active_account(
                        session.session_id,
                        user_id,
                        replacement.id,
                    )

    def set_session_cookie(
        self,
        response: Response,
        session: AuthSessionRecord,
    ) -> None:
        same_site = "none" if self.settings.session_cookie_secure else "lax"
        expires_at = session.session_expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        else:
            expires_at = expires_at.astimezone(UTC)
        response.set_cookie(
            key=self.settings.session_cookie_name,
            value=session.session_id,
            httponly=True,
            samesite=same_site,
            secure=self.settings.session_cookie_secure,
            path="/",
            max_age=self.settings.session_ttl_seconds,
            expires=expires_at,
        )

    def clear_session_cookie(self, response: Response) -> None:
        same_site = "none" if self.settings.session_cookie_secure else "lax"
        response.delete_cookie(
            key=self.settings.session_cookie_name,
            path="/",
            secure=self.settings.session_cookie_secure,
            httponly=True,
            samesite=same_site,
        )

    def error_redirect(self, message: str) -> str:
        return self._absolute_redirect(f"/auth?error={quote(message)}")

    def _absolute_redirect(self, path: str) -> str:
        return f"{self.settings.web_base_url.rstrip('/')}{path}"

    def _normalize_redirect_to(self, value: str | None) -> str:
        if not value or not value.startswith("/") or value.startswith("//"):
            return "/mail"
        return value

    def _is_session_expired(
        self,
        session: AuthSessionRecord,
        now: datetime,
    ) -> bool:
        return session.session_expires_at <= now

    def _is_google_token_expired(
        self,
        session: AuthSessionRecord,
        now: datetime,
    ) -> bool:
        if session.expires_at is None:
            return False
        return session.expires_at <= now + timedelta(seconds=30)

    def _session_ttl(self) -> timedelta:
        return timedelta(seconds=self.settings.session_ttl_seconds)

    def _supported_provider(self, provider: str) -> str:
        normalized = canonical_provider(provider)
        if not normalized:
            raise ValueError("provider is required")
        return normalized

    def _is_google_provider(self, provider: str | None) -> bool:
        return canonical_provider(provider) == "google_gmail"

    def _linked_account_access(
        self, account: LinkedAccountRecord
    ) -> LinkedAccountAccess | None:
        credential = self.store.get_provider_credential(account.id)
        if credential is None:
            return None

        if self._is_google_provider(account.provider):
            now = datetime.now(UTC)
            if (
                credential.expires_at is not None
                and credential.expires_at <= now + timedelta(seconds=30)
            ):
                if not credential.refresh_token:
                    return None
                try:
                    refreshed = self.google_client.refresh_access_token(
                        credential.refresh_token
                    )
                except RuntimeError:
                    return None
                credential = ProviderCredentialRecord(
                    linked_account_id=account.id,
                    access_token=refreshed.access_token,
                    refresh_token=refreshed.refresh_token or credential.refresh_token,
                    scope=refreshed.scope or credential.scope,
                    expires_at=refreshed.expires_at,
                    created_at=credential.created_at,
                    updated_at=datetime.now(UTC),
                )
                self.store.upsert_provider_credential(credential)

        return LinkedAccountAccess(account=account, credential=credential)
