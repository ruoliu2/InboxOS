from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any, Protocol
from urllib.parse import unquote, urlparse

import psycopg
from cryptography.fernet import Fernet
from psycopg.rows import dict_row

from app.services.id_factory import new_id


def canonical_provider(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if not normalized:
        return ""
    if normalized in {"google", "gmail", "google_gmail"}:
        return "google_gmail"
    return normalized


@dataclass
class OAuthStateRecord:
    state: str
    redirect_to: str
    created_at: datetime


@dataclass
class OAuthFlowRecord:
    state: str
    provider: str
    intent: str
    user_id: str | None
    redirect_to: str
    pkce_verifier: str | None
    requested_scopes: list[str]
    expires_at: datetime
    consumed_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass
class AppUserRecord:
    id: str
    primary_email: str | None
    display_name: str | None
    avatar_url: str | None
    created_at: datetime
    updated_at: datetime


@dataclass
class LinkedAccountRecord:
    id: str
    user_id: str
    provider: str
    provider_account_id: str
    provider_account_ref: str | None
    display_name: str | None
    avatar_url: str | None
    status: str
    capabilities: list[str]
    metadata: dict[str, Any]
    last_synced_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass
class ProviderCredentialRecord:
    linked_account_id: str
    access_token: str
    refresh_token: str | None
    scope: str | None
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass
class AuthSessionRecord:
    session_id: str
    provider: str
    account_email: str | None
    account_name: str | None
    account_picture: str | None
    access_token: str
    refresh_token: str | None
    scope: str | None
    expires_at: datetime | None
    session_expires_at: datetime
    created_at: datetime
    updated_at: datetime
    user_id: str | None = None
    active_linked_account_id: str | None = None


class AuthStore(Protocol):
    def clear(self) -> None: ...

    def save_oauth_state(self, state: OAuthStateRecord) -> None: ...

    def pop_oauth_state(self, state: str) -> OAuthStateRecord | None: ...

    def save_oauth_flow(self, flow: OAuthFlowRecord) -> None: ...

    def consume_oauth_flow(self, state: str) -> OAuthFlowRecord | None: ...

    def upsert_user(self, user: AppUserRecord) -> AppUserRecord: ...

    def get_user(self, user_id: str) -> AppUserRecord | None: ...

    def find_user_by_primary_email(self, email: str) -> AppUserRecord | None: ...

    def upsert_linked_account(
        self, account: LinkedAccountRecord
    ) -> LinkedAccountRecord: ...

    def find_linked_account(
        self, provider: str, provider_account_id: str
    ) -> LinkedAccountRecord | None: ...

    def get_linked_account(
        self, user_id: str, linked_account_id: str
    ) -> LinkedAccountRecord | None: ...

    def get_linked_account_by_id(
        self, linked_account_id: str
    ) -> LinkedAccountRecord | None: ...

    def list_linked_accounts(self, user_id: str) -> list[LinkedAccountRecord]: ...

    def upsert_provider_credential(
        self, credential: ProviderCredentialRecord
    ) -> None: ...

    def get_provider_credential(
        self, linked_account_id: str
    ) -> ProviderCredentialRecord | None: ...

    def create_or_update_session(
        self, session: AuthSessionRecord
    ) -> AuthSessionRecord: ...

    def upsert_session(self, session: AuthSessionRecord) -> None: ...

    def update_session_expiry(
        self, session_id: str, session_expires_at: datetime, updated_at: datetime
    ) -> None: ...

    def get_session(self, session_id: str) -> AuthSessionRecord | None: ...

    def delete_session(self, session_id: str) -> None: ...

    def set_active_account(
        self, session_id: str, user_id: str, linked_account_id: str
    ) -> None: ...

    def disconnect_account(self, user_id: str, linked_account_id: str) -> None: ...


class TokenCipher:
    def __init__(self, key: str) -> None:
        self.fernet = Fernet(self._resolve_fernet_key(key))

    def _resolve_fernet_key(self, key: str) -> bytes:
        encoded = key.encode("utf-8")
        try:
            Fernet(encoded)
            return encoded
        except ValueError:
            digest = hashlib.sha256(encoded).digest()
            return base64.urlsafe_b64encode(digest)

    def encrypt(self, value: str | None) -> str | None:
        if not value:
            return None
        return self.fernet.encrypt(value.encode("utf-8")).decode("utf-8")

    def decrypt(self, value: str | None) -> str | None:
        if not value:
            return None
        return self.fernet.decrypt(value.encode("utf-8")).decode("utf-8")


class _BaseAuthStore:
    def __init__(self, oauth_state_ttl_seconds: int, encryption_key: str) -> None:
        self.oauth_state_ttl = timedelta(seconds=oauth_state_ttl_seconds)
        self._lock = Lock()
        self.cipher = TokenCipher(encryption_key)

    def save_oauth_state(self, state: OAuthStateRecord) -> None:
        self.save_oauth_flow(
            OAuthFlowRecord(
                state=state.state,
                provider="google_gmail",
                intent="sign_in",
                user_id=None,
                redirect_to=state.redirect_to,
                pkce_verifier=None,
                requested_scopes=[],
                expires_at=state.created_at + self.oauth_state_ttl,
                consumed_at=None,
                created_at=state.created_at,
                updated_at=state.created_at,
            )
        )

    def pop_oauth_state(self, state: str) -> OAuthStateRecord | None:
        flow = self.consume_oauth_flow(state)
        if flow is None:
            return None
        return OAuthStateRecord(
            state=flow.state,
            redirect_to=flow.redirect_to,
            created_at=flow.created_at,
        )

    def create_or_update_session(self, session: AuthSessionRecord) -> AuthSessionRecord:
        self.upsert_session(session)
        stored = self.get_session(session.session_id)
        if stored is None:
            raise RuntimeError("Failed to hydrate persisted auth session.")
        return stored

    def _normalize_email(self, value: str | None) -> str | None:
        normalized = value.strip().lower() if value else None
        return normalized or None

    def _serialize_datetime(self, value: datetime | None) -> str | None:
        return value.isoformat() if value is not None else None

    def _parse_optional_datetime(self, value: str | datetime | None) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(value)

    def _parse_datetime(self, value: str | datetime) -> datetime:
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(value)

    def _dump_json(self, value: list[str] | dict[str, Any]) -> str:
        return json.dumps(value)

    def _load_list(self, value: str | list[str] | None) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value]
        payload = json.loads(value)
        return [str(item) for item in payload] if isinstance(payload, list) else []

    def _load_dict(self, value: str | dict[str, Any] | None) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        payload = json.loads(value)
        return payload if isinstance(payload, dict) else {}

    def _ensure_user_for_session(self, session: AuthSessionRecord) -> AppUserRecord:
        existing = None
        if session.user_id:
            existing = self.get_user(session.user_id)
        elif session.account_email:
            existing = self.find_user_by_primary_email(session.account_email)

        now = session.updated_at
        user = AppUserRecord(
            id=(
                existing.id
                if existing is not None
                else (session.user_id or new_id("usr"))
            ),
            primary_email=self._normalize_email(session.account_email)
            or (existing.primary_email if existing is not None else None),
            display_name=session.account_name
            or (existing.display_name if existing else None),
            avatar_url=session.account_picture
            or (existing.avatar_url if existing else None),
            created_at=(
                existing.created_at if existing is not None else session.created_at
            ),
            updated_at=now,
        )
        return self.upsert_user(user)

    def _ensure_account_for_session(
        self, session: AuthSessionRecord, user: AppUserRecord
    ) -> LinkedAccountRecord:
        provider = self._require_provider(session.provider)
        provider_account_id = self._normalize_email(session.account_email) or user.id
        existing = self.find_linked_account(provider, provider_account_id)
        now = session.updated_at
        account = LinkedAccountRecord(
            id=(
                existing.id
                if existing is not None
                else (session.active_linked_account_id or new_id("acct"))
            ),
            user_id=user.id,
            provider=provider,
            provider_account_id=provider_account_id,
            provider_account_ref=session.account_email,
            display_name=session.account_name,
            avatar_url=session.account_picture,
            status="active",
            capabilities=["mail", "calendar"],
            metadata={},
            last_synced_at=None,
            created_at=(
                existing.created_at if existing is not None else session.created_at
            ),
            updated_at=now,
        )
        return self.upsert_linked_account(account)

    def _require_provider(self, value: str | None) -> str:
        provider = canonical_provider(value)
        if not provider:
            raise ValueError("provider is required")
        return provider


class SQLiteAuthStore(_BaseAuthStore):
    def __init__(
        self, database_url: str, oauth_state_ttl_seconds: int, encryption_key: str
    ) -> None:
        super().__init__(oauth_state_ttl_seconds, encryption_key)
        parsed = urlparse(database_url)
        if parsed.scheme != "sqlite":
            raise ValueError(f"Unsupported SQLite database URL: {database_url}")
        raw_path = unquote(parsed.path)
        self.db_path = Path(raw_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def clear(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM provider_credentials")
            connection.execute("DELETE FROM app_sessions")
            connection.execute("DELETE FROM oauth_flows")
            connection.execute("DELETE FROM linked_accounts")
            connection.execute("DELETE FROM users")
            connection.commit()

    def save_oauth_flow(self, flow: OAuthFlowRecord) -> None:
        with self._lock, self._connect() as connection:
            self._delete_expired_oauth_flows(connection)
            connection.execute(
                """
                INSERT INTO oauth_flows (
                    state,
                    provider,
                    intent,
                    user_id,
                    redirect_to,
                    pkce_verifier,
                    requested_scopes_json,
                    expires_at,
                    consumed_at,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(state) DO UPDATE SET
                    provider = excluded.provider,
                    intent = excluded.intent,
                    user_id = excluded.user_id,
                    redirect_to = excluded.redirect_to,
                    pkce_verifier = excluded.pkce_verifier,
                    requested_scopes_json = excluded.requested_scopes_json,
                    expires_at = excluded.expires_at,
                    consumed_at = excluded.consumed_at,
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at
                """,
                (
                    flow.state,
                    canonical_provider(flow.provider),
                    flow.intent,
                    flow.user_id,
                    flow.redirect_to,
                    flow.pkce_verifier,
                    self._dump_json(flow.requested_scopes),
                    flow.expires_at.isoformat(),
                    self._serialize_datetime(flow.consumed_at),
                    flow.created_at.isoformat(),
                    flow.updated_at.isoformat(),
                ),
            )
            connection.commit()

    def consume_oauth_flow(self, state: str) -> OAuthFlowRecord | None:
        cutoff = datetime.now(UTC)
        with self._lock, self._connect() as connection:
            self._delete_expired_oauth_flows(connection, cutoff=cutoff)
            row = connection.execute(
                """
                SELECT state, provider, intent, user_id, redirect_to, pkce_verifier,
                       requested_scopes_json, expires_at, consumed_at, created_at,
                       updated_at
                FROM oauth_flows
                WHERE state = ?
                """,
                (state,),
            ).fetchone()
            if row is None:
                return None
            if row["consumed_at"] is not None:
                return None
            connection.execute(
                """
                UPDATE oauth_flows
                SET consumed_at = ?, updated_at = ?
                WHERE state = ?
                """,
                (cutoff.isoformat(), cutoff.isoformat(), state),
            )
            connection.commit()

        flow = self._row_to_oauth_flow(row)
        if flow.expires_at <= cutoff:
            return None
        flow.consumed_at = cutoff
        flow.updated_at = cutoff
        return flow

    def upsert_user(self, user: AppUserRecord) -> AppUserRecord:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO users (
                    id,
                    primary_email,
                    display_name,
                    avatar_url,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    primary_email = excluded.primary_email,
                    display_name = excluded.display_name,
                    avatar_url = excluded.avatar_url,
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at
                """,
                (
                    user.id,
                    self._normalize_email(user.primary_email),
                    user.display_name,
                    user.avatar_url,
                    user.created_at.isoformat(),
                    user.updated_at.isoformat(),
                ),
            )
            connection.commit()
        return user

    def get_user(self, user_id: str) -> AppUserRecord | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, primary_email, display_name, avatar_url, created_at, updated_at
                FROM users
                WHERE id = ?
                """,
                (user_id,),
            ).fetchone()
        return self._row_to_user(row) if row is not None else None

    def find_user_by_primary_email(self, email: str) -> AppUserRecord | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, primary_email, display_name, avatar_url, created_at, updated_at
                FROM users
                WHERE primary_email = ?
                """,
                (self._normalize_email(email),),
            ).fetchone()
        return self._row_to_user(row) if row is not None else None

    def upsert_linked_account(
        self, account: LinkedAccountRecord
    ) -> LinkedAccountRecord:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO linked_accounts (
                    id,
                    user_id,
                    provider,
                    provider_account_id,
                    provider_account_ref,
                    display_name,
                    avatar_url,
                    status,
                    capabilities_json,
                    metadata_json,
                    last_synced_at,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, provider_account_id) DO UPDATE SET
                    user_id = excluded.user_id,
                    provider_account_ref = excluded.provider_account_ref,
                    display_name = excluded.display_name,
                    avatar_url = excluded.avatar_url,
                    status = excluded.status,
                    capabilities_json = excluded.capabilities_json,
                    metadata_json = excluded.metadata_json,
                    last_synced_at = excluded.last_synced_at,
                    updated_at = excluded.updated_at
                """,
                (
                    account.id,
                    account.user_id,
                    canonical_provider(account.provider),
                    account.provider_account_id,
                    account.provider_account_ref,
                    account.display_name,
                    account.avatar_url,
                    account.status,
                    self._dump_json(account.capabilities),
                    self._dump_json(account.metadata),
                    self._serialize_datetime(account.last_synced_at),
                    account.created_at.isoformat(),
                    account.updated_at.isoformat(),
                ),
            )
            connection.commit()
            row = connection.execute(
                """
                SELECT id, user_id, provider, provider_account_id, provider_account_ref,
                       display_name, avatar_url, status, capabilities_json, metadata_json,
                       last_synced_at, created_at, updated_at
                FROM linked_accounts
                WHERE provider = ? AND provider_account_id = ?
                """,
                (canonical_provider(account.provider), account.provider_account_id),
            ).fetchone()
        if row is None:
            raise RuntimeError("Failed to persist linked account.")
        return self._row_to_linked_account(row)

    def find_linked_account(
        self, provider: str, provider_account_id: str
    ) -> LinkedAccountRecord | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, user_id, provider, provider_account_id, provider_account_ref,
                       display_name, avatar_url, status, capabilities_json, metadata_json,
                       last_synced_at, created_at, updated_at
                FROM linked_accounts
                WHERE provider = ? AND provider_account_id = ?
                """,
                (canonical_provider(provider), provider_account_id),
            ).fetchone()
        return self._row_to_linked_account(row) if row is not None else None

    def get_linked_account(
        self, user_id: str, linked_account_id: str
    ) -> LinkedAccountRecord | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, user_id, provider, provider_account_id, provider_account_ref,
                       display_name, avatar_url, status, capabilities_json, metadata_json,
                       last_synced_at, created_at, updated_at
                FROM linked_accounts
                WHERE id = ? AND user_id = ?
                """,
                (linked_account_id, user_id),
            ).fetchone()
        return self._row_to_linked_account(row) if row is not None else None

    def get_linked_account_by_id(
        self, linked_account_id: str
    ) -> LinkedAccountRecord | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, user_id, provider, provider_account_id, provider_account_ref,
                       display_name, avatar_url, status, capabilities_json, metadata_json,
                       last_synced_at, created_at, updated_at
                FROM linked_accounts
                WHERE id = ?
                """,
                (linked_account_id,),
            ).fetchone()
        return self._row_to_linked_account(row) if row is not None else None

    def list_linked_accounts(self, user_id: str) -> list[LinkedAccountRecord]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, user_id, provider, provider_account_id, provider_account_ref,
                       display_name, avatar_url, status, capabilities_json, metadata_json,
                       last_synced_at, created_at, updated_at
                FROM linked_accounts
                WHERE user_id = ?
                ORDER BY created_at ASC
                """,
                (user_id,),
            ).fetchall()
        return [self._row_to_linked_account(row) for row in rows]

    def upsert_provider_credential(self, credential: ProviderCredentialRecord) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO provider_credentials (
                    linked_account_id,
                    access_token_encrypted,
                    refresh_token_encrypted,
                    scope,
                    expires_at,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(linked_account_id) DO UPDATE SET
                    access_token_encrypted = excluded.access_token_encrypted,
                    refresh_token_encrypted = excluded.refresh_token_encrypted,
                    scope = excluded.scope,
                    expires_at = excluded.expires_at,
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at
                """,
                (
                    credential.linked_account_id,
                    self.cipher.encrypt(credential.access_token),
                    self.cipher.encrypt(credential.refresh_token),
                    credential.scope,
                    self._serialize_datetime(credential.expires_at),
                    credential.created_at.isoformat(),
                    credential.updated_at.isoformat(),
                ),
            )
            connection.commit()

    def get_provider_credential(
        self, linked_account_id: str
    ) -> ProviderCredentialRecord | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT linked_account_id, access_token_encrypted, refresh_token_encrypted,
                       scope, expires_at, created_at, updated_at
                FROM provider_credentials
                WHERE linked_account_id = ?
                """,
                (linked_account_id,),
            ).fetchone()
        if row is None:
            return None
        return ProviderCredentialRecord(
            linked_account_id=str(row["linked_account_id"]),
            access_token=self.cipher.decrypt(row["access_token_encrypted"]) or "",
            refresh_token=self.cipher.decrypt(row["refresh_token_encrypted"]),
            scope=row["scope"],
            expires_at=self._parse_optional_datetime(row["expires_at"]),
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
        )

    def upsert_session(self, session: AuthSessionRecord) -> None:
        user = self._ensure_user_for_session(session)
        account = self._ensure_account_for_session(session, user)
        credential = ProviderCredentialRecord(
            linked_account_id=account.id,
            access_token=session.access_token,
            refresh_token=session.refresh_token,
            scope=session.scope,
            expires_at=session.expires_at,
            created_at=session.created_at,
            updated_at=session.updated_at,
        )
        self.upsert_provider_credential(credential)
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO app_sessions (
                    session_id,
                    user_id,
                    active_linked_account_id,
                    session_expires_at,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    user_id = excluded.user_id,
                    active_linked_account_id = excluded.active_linked_account_id,
                    session_expires_at = excluded.session_expires_at,
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at
                """,
                (
                    session.session_id,
                    user.id,
                    account.id,
                    session.session_expires_at.isoformat(),
                    session.created_at.isoformat(),
                    session.updated_at.isoformat(),
                ),
            )
            connection.commit()

    def update_session_expiry(
        self, session_id: str, session_expires_at: datetime, updated_at: datetime
    ) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE app_sessions
                SET session_expires_at = ?, updated_at = ?
                WHERE session_id = ?
                """,
                (
                    session_expires_at.isoformat(),
                    updated_at.isoformat(),
                    session_id,
                ),
            )
            connection.commit()

    def get_session(self, session_id: str) -> AuthSessionRecord | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT s.session_id, s.user_id, s.active_linked_account_id,
                       s.session_expires_at, s.created_at, s.updated_at,
                       a.provider, a.provider_account_ref, a.display_name, a.avatar_url,
                       c.access_token_encrypted, c.refresh_token_encrypted, c.scope,
                       c.expires_at
                FROM app_sessions s
                LEFT JOIN linked_accounts a ON a.id = s.active_linked_account_id
                LEFT JOIN provider_credentials c ON c.linked_account_id = a.id
                WHERE s.session_id = ?
                """,
                (session_id,),
            ).fetchone()
        return self._row_to_auth_session(row) if row is not None else None

    def delete_session(self, session_id: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM app_sessions WHERE session_id = ?", (session_id,)
            )
            connection.commit()

    def set_active_account(
        self, session_id: str, user_id: str, linked_account_id: str
    ) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE app_sessions
                SET active_linked_account_id = ?, updated_at = ?
                WHERE session_id = ? AND user_id = ?
                """,
                (
                    linked_account_id,
                    datetime.now(UTC).isoformat(),
                    session_id,
                    user_id,
                ),
            )
            connection.commit()

    def disconnect_account(self, user_id: str, linked_account_id: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE linked_accounts
                SET status = 'disconnected', updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (datetime.now(UTC).isoformat(), linked_account_id, user_id),
            )
            connection.execute(
                "DELETE FROM provider_credentials WHERE linked_account_id = ?",
                (linked_account_id,),
            )
            connection.execute(
                """
                UPDATE app_sessions
                SET active_linked_account_id = NULL, updated_at = ?
                WHERE user_id = ? AND active_linked_account_id = ?
                """,
                (datetime.now(UTC).isoformat(), user_id, linked_account_id),
            )
            connection.commit()

    def _init_db(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    primary_email TEXT UNIQUE,
                    display_name TEXT,
                    avatar_url TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS linked_accounts (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    provider_account_id TEXT NOT NULL,
                    provider_account_ref TEXT,
                    display_name TEXT,
                    avatar_url TEXT,
                    status TEXT NOT NULL,
                    capabilities_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    last_synced_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(provider, provider_account_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS provider_credentials (
                    linked_account_id TEXT PRIMARY KEY,
                    access_token_encrypted TEXT NOT NULL,
                    refresh_token_encrypted TEXT,
                    scope TEXT,
                    expires_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS oauth_flows (
                    state TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    intent TEXT NOT NULL,
                    user_id TEXT,
                    redirect_to TEXT NOT NULL,
                    pkce_verifier TEXT,
                    requested_scopes_json TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    consumed_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS app_sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    active_linked_account_id TEXT,
                    session_expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_linked_accounts_user
                ON linked_accounts (user_id, created_at ASC)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_oauth_flows_expires
                ON oauth_flows (expires_at)
                """
            )
            connection.commit()

    def _delete_expired_oauth_flows(
        self,
        connection: sqlite3.Connection,
        *,
        cutoff: datetime | None = None,
    ) -> None:
        effective_cutoff = cutoff or datetime.now(UTC)
        connection.execute(
            "DELETE FROM oauth_flows WHERE expires_at <= ?",
            (effective_cutoff.isoformat(),),
        )

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()

    def _row_to_user(self, row: sqlite3.Row | None) -> AppUserRecord | None:
        if row is None:
            return None
        return AppUserRecord(
            id=row["id"],
            primary_email=row["primary_email"],
            display_name=row["display_name"],
            avatar_url=row["avatar_url"],
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
        )

    def _row_to_linked_account(self, row: sqlite3.Row) -> LinkedAccountRecord:
        return LinkedAccountRecord(
            id=row["id"],
            user_id=row["user_id"],
            provider=row["provider"],
            provider_account_id=row["provider_account_id"],
            provider_account_ref=row["provider_account_ref"],
            display_name=row["display_name"],
            avatar_url=row["avatar_url"],
            status=row["status"],
            capabilities=self._load_list(row["capabilities_json"]),
            metadata=self._load_dict(row["metadata_json"]),
            last_synced_at=self._parse_optional_datetime(row["last_synced_at"]),
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
        )

    def _row_to_oauth_flow(self, row: sqlite3.Row) -> OAuthFlowRecord:
        return OAuthFlowRecord(
            state=row["state"],
            provider=row["provider"],
            intent=row["intent"],
            user_id=row["user_id"],
            redirect_to=row["redirect_to"],
            pkce_verifier=row["pkce_verifier"],
            requested_scopes=self._load_list(row["requested_scopes_json"]),
            expires_at=self._parse_datetime(row["expires_at"]),
            consumed_at=self._parse_optional_datetime(row["consumed_at"]),
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
        )

    def _row_to_auth_session(self, row: sqlite3.Row) -> AuthSessionRecord:
        return AuthSessionRecord(
            session_id=row["session_id"],
            user_id=row["user_id"],
            active_linked_account_id=row["active_linked_account_id"],
            provider=row["provider"] or "unknown",
            account_email=row["provider_account_ref"],
            account_name=row["display_name"],
            account_picture=row["avatar_url"],
            access_token=self.cipher.decrypt(row["access_token_encrypted"]) or "",
            refresh_token=self.cipher.decrypt(row["refresh_token_encrypted"]),
            scope=row["scope"],
            expires_at=self._parse_optional_datetime(row["expires_at"]),
            session_expires_at=self._parse_datetime(row["session_expires_at"]),
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
        )


class PostgresAuthStore(_BaseAuthStore):
    def __init__(
        self, database_url: str, oauth_state_ttl_seconds: int, encryption_key: str
    ) -> None:
        super().__init__(oauth_state_ttl_seconds, encryption_key)
        self.database_url = database_url
        self._init_db()

    def clear(self) -> None:
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM provider_credentials")
                cursor.execute("DELETE FROM app_sessions")
                cursor.execute("DELETE FROM oauth_flows")
                cursor.execute("DELETE FROM linked_accounts")
                cursor.execute("DELETE FROM users")
            connection.commit()

    def save_oauth_flow(self, flow: OAuthFlowRecord) -> None:
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM oauth_flows WHERE expires_at <= %s",
                    (datetime.now(UTC),),
                )
                cursor.execute(
                    """
                    INSERT INTO oauth_flows (
                        state,
                        provider,
                        intent,
                        user_id,
                        redirect_to,
                        pkce_verifier,
                        requested_scopes_json,
                        expires_at,
                        consumed_at,
                        created_at,
                        updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (state) DO UPDATE SET
                        provider = excluded.provider,
                        intent = excluded.intent,
                        user_id = excluded.user_id,
                        redirect_to = excluded.redirect_to,
                        pkce_verifier = excluded.pkce_verifier,
                        requested_scopes_json = excluded.requested_scopes_json,
                        expires_at = excluded.expires_at,
                        consumed_at = excluded.consumed_at,
                        created_at = excluded.created_at,
                        updated_at = excluded.updated_at
                    """,
                    (
                        flow.state,
                        canonical_provider(flow.provider),
                        flow.intent,
                        flow.user_id,
                        flow.redirect_to,
                        flow.pkce_verifier,
                        self._dump_json(flow.requested_scopes),
                        flow.expires_at,
                        flow.consumed_at,
                        flow.created_at,
                        flow.updated_at,
                    ),
                )
            connection.commit()

    def consume_oauth_flow(self, state: str) -> OAuthFlowRecord | None:
        cutoff = datetime.now(UTC)
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM oauth_flows WHERE expires_at <= %s", (cutoff,)
                )
                cursor.execute(
                    """
                    SELECT state, provider, intent, user_id, redirect_to, pkce_verifier,
                           requested_scopes_json, expires_at, consumed_at, created_at,
                           updated_at
                    FROM oauth_flows
                    WHERE state = %s
                    """,
                    (state,),
                )
                row = cursor.fetchone()
                if row is None or row["consumed_at"] is not None:
                    return None
                cursor.execute(
                    """
                    UPDATE oauth_flows
                    SET consumed_at = %s, updated_at = %s
                    WHERE state = %s
                    """,
                    (cutoff, cutoff, state),
                )
            connection.commit()
        flow = self._pg_row_to_oauth_flow(row)
        if flow.expires_at <= cutoff:
            return None
        flow.consumed_at = cutoff
        flow.updated_at = cutoff
        return flow

    def upsert_user(self, user: AppUserRecord) -> AppUserRecord:
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO users (
                        id,
                        primary_email,
                        display_name,
                        avatar_url,
                        created_at,
                        updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        primary_email = excluded.primary_email,
                        display_name = excluded.display_name,
                        avatar_url = excluded.avatar_url,
                        created_at = excluded.created_at,
                        updated_at = excluded.updated_at
                    """,
                    (
                        user.id,
                        self._normalize_email(user.primary_email),
                        user.display_name,
                        user.avatar_url,
                        user.created_at,
                        user.updated_at,
                    ),
                )
            connection.commit()
        return user

    def get_user(self, user_id: str) -> AppUserRecord | None:
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, primary_email, display_name, avatar_url, created_at, updated_at
                    FROM users
                    WHERE id = %s
                    """,
                    (user_id,),
                )
                row = cursor.fetchone()
        return self._pg_row_to_user(row) if row is not None else None

    def find_user_by_primary_email(self, email: str) -> AppUserRecord | None:
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, primary_email, display_name, avatar_url, created_at, updated_at
                    FROM users
                    WHERE primary_email = %s
                    """,
                    (self._normalize_email(email),),
                )
                row = cursor.fetchone()
        return self._pg_row_to_user(row) if row is not None else None

    def upsert_linked_account(
        self, account: LinkedAccountRecord
    ) -> LinkedAccountRecord:
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO linked_accounts (
                        id,
                        user_id,
                        provider,
                        provider_account_id,
                        provider_account_ref,
                        display_name,
                        avatar_url,
                        status,
                        capabilities_json,
                        metadata_json,
                        last_synced_at,
                        created_at,
                        updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (provider, provider_account_id) DO UPDATE SET
                        user_id = excluded.user_id,
                        provider_account_ref = excluded.provider_account_ref,
                        display_name = excluded.display_name,
                        avatar_url = excluded.avatar_url,
                        status = excluded.status,
                        capabilities_json = excluded.capabilities_json,
                        metadata_json = excluded.metadata_json,
                        last_synced_at = excluded.last_synced_at,
                        updated_at = excluded.updated_at
                    RETURNING id, user_id, provider, provider_account_id, provider_account_ref,
                              display_name, avatar_url, status, capabilities_json,
                              metadata_json, last_synced_at, created_at, updated_at
                    """,
                    (
                        account.id,
                        account.user_id,
                        canonical_provider(account.provider),
                        account.provider_account_id,
                        account.provider_account_ref,
                        account.display_name,
                        account.avatar_url,
                        account.status,
                        self._dump_json(account.capabilities),
                        self._dump_json(account.metadata),
                        account.last_synced_at,
                        account.created_at,
                        account.updated_at,
                    ),
                )
                row = cursor.fetchone()
            connection.commit()
        if row is None:
            raise RuntimeError("Failed to persist linked account.")
        return self._pg_row_to_linked_account(row)

    def find_linked_account(
        self, provider: str, provider_account_id: str
    ) -> LinkedAccountRecord | None:
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, user_id, provider, provider_account_id, provider_account_ref,
                           display_name, avatar_url, status, capabilities_json, metadata_json,
                           last_synced_at, created_at, updated_at
                    FROM linked_accounts
                    WHERE provider = %s AND provider_account_id = %s
                    """,
                    (canonical_provider(provider), provider_account_id),
                )
                row = cursor.fetchone()
        return self._pg_row_to_linked_account(row) if row is not None else None

    def get_linked_account(
        self, user_id: str, linked_account_id: str
    ) -> LinkedAccountRecord | None:
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, user_id, provider, provider_account_id, provider_account_ref,
                           display_name, avatar_url, status, capabilities_json, metadata_json,
                           last_synced_at, created_at, updated_at
                    FROM linked_accounts
                    WHERE id = %s AND user_id = %s
                    """,
                    (linked_account_id, user_id),
                )
                row = cursor.fetchone()
        return self._pg_row_to_linked_account(row) if row is not None else None

    def get_linked_account_by_id(
        self, linked_account_id: str
    ) -> LinkedAccountRecord | None:
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, user_id, provider, provider_account_id, provider_account_ref,
                           display_name, avatar_url, status, capabilities_json, metadata_json,
                           last_synced_at, created_at, updated_at
                    FROM linked_accounts
                    WHERE id = %s
                    """,
                    (linked_account_id,),
                )
                row = cursor.fetchone()
        return self._pg_row_to_linked_account(row) if row is not None else None

    def list_linked_accounts(self, user_id: str) -> list[LinkedAccountRecord]:
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, user_id, provider, provider_account_id, provider_account_ref,
                           display_name, avatar_url, status, capabilities_json, metadata_json,
                           last_synced_at, created_at, updated_at
                    FROM linked_accounts
                    WHERE user_id = %s
                    ORDER BY created_at ASC
                    """,
                    (user_id,),
                )
                rows = cursor.fetchall()
        return [self._pg_row_to_linked_account(row) for row in rows]

    def upsert_provider_credential(self, credential: ProviderCredentialRecord) -> None:
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO provider_credentials (
                        linked_account_id,
                        access_token_encrypted,
                        refresh_token_encrypted,
                        scope,
                        expires_at,
                        created_at,
                        updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (linked_account_id) DO UPDATE SET
                        access_token_encrypted = excluded.access_token_encrypted,
                        refresh_token_encrypted = excluded.refresh_token_encrypted,
                        scope = excluded.scope,
                        expires_at = excluded.expires_at,
                        created_at = excluded.created_at,
                        updated_at = excluded.updated_at
                    """,
                    (
                        credential.linked_account_id,
                        self.cipher.encrypt(credential.access_token),
                        self.cipher.encrypt(credential.refresh_token),
                        credential.scope,
                        credential.expires_at,
                        credential.created_at,
                        credential.updated_at,
                    ),
                )
            connection.commit()

    def get_provider_credential(
        self, linked_account_id: str
    ) -> ProviderCredentialRecord | None:
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT linked_account_id, access_token_encrypted, refresh_token_encrypted,
                           scope, expires_at, created_at, updated_at
                    FROM provider_credentials
                    WHERE linked_account_id = %s
                    """,
                    (linked_account_id,),
                )
                row = cursor.fetchone()
        if row is None:
            return None
        return ProviderCredentialRecord(
            linked_account_id=str(row["linked_account_id"]),
            access_token=self.cipher.decrypt(row["access_token_encrypted"]) or "",
            refresh_token=self.cipher.decrypt(row["refresh_token_encrypted"]),
            scope=row["scope"],
            expires_at=self._parse_optional_datetime(row["expires_at"]),
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
        )

    def upsert_session(self, session: AuthSessionRecord) -> None:
        user = self._ensure_user_for_session(session)
        account = self._ensure_account_for_session(session, user)
        self.upsert_provider_credential(
            ProviderCredentialRecord(
                linked_account_id=account.id,
                access_token=session.access_token,
                refresh_token=session.refresh_token,
                scope=session.scope,
                expires_at=session.expires_at,
                created_at=session.created_at,
                updated_at=session.updated_at,
            )
        )
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO app_sessions (
                        session_id,
                        user_id,
                        active_linked_account_id,
                        session_expires_at,
                        created_at,
                        updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (session_id) DO UPDATE SET
                        user_id = excluded.user_id,
                        active_linked_account_id = excluded.active_linked_account_id,
                        session_expires_at = excluded.session_expires_at,
                        created_at = excluded.created_at,
                        updated_at = excluded.updated_at
                    """,
                    (
                        session.session_id,
                        user.id,
                        account.id,
                        session.session_expires_at,
                        session.created_at,
                        session.updated_at,
                    ),
                )
            connection.commit()

    def update_session_expiry(
        self, session_id: str, session_expires_at: datetime, updated_at: datetime
    ) -> None:
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE app_sessions
                    SET session_expires_at = %s, updated_at = %s
                    WHERE session_id = %s
                    """,
                    (session_expires_at, updated_at, session_id),
                )
            connection.commit()

    def get_session(self, session_id: str) -> AuthSessionRecord | None:
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT s.session_id, s.user_id, s.active_linked_account_id,
                           s.session_expires_at, s.created_at, s.updated_at,
                           a.provider, a.provider_account_ref, a.display_name, a.avatar_url,
                           c.access_token_encrypted, c.refresh_token_encrypted, c.scope,
                           c.expires_at
                    FROM app_sessions s
                    LEFT JOIN linked_accounts a ON a.id = s.active_linked_account_id
                    LEFT JOIN provider_credentials c ON c.linked_account_id = a.id
                    WHERE s.session_id = %s
                    """,
                    (session_id,),
                )
                row = cursor.fetchone()
        return self._pg_row_to_auth_session(row) if row is not None else None

    def delete_session(self, session_id: str) -> None:
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM app_sessions WHERE session_id = %s", (session_id,)
                )
            connection.commit()

    def set_active_account(
        self, session_id: str, user_id: str, linked_account_id: str
    ) -> None:
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE app_sessions
                    SET active_linked_account_id = %s, updated_at = %s
                    WHERE session_id = %s AND user_id = %s
                    """,
                    (linked_account_id, datetime.now(UTC), session_id, user_id),
                )
            connection.commit()

    def disconnect_account(self, user_id: str, linked_account_id: str) -> None:
        with self._lock, self._connect() as connection:
            now = datetime.now(UTC)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE linked_accounts
                    SET status = 'disconnected', updated_at = %s
                    WHERE id = %s AND user_id = %s
                    """,
                    (now, linked_account_id, user_id),
                )
                cursor.execute(
                    "DELETE FROM provider_credentials WHERE linked_account_id = %s",
                    (linked_account_id,),
                )
                cursor.execute(
                    """
                    UPDATE app_sessions
                    SET active_linked_account_id = NULL, updated_at = %s
                    WHERE user_id = %s AND active_linked_account_id = %s
                    """,
                    (now, user_id, linked_account_id),
                )
            connection.commit()

    def _init_db(self) -> None:
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS users (
                        id TEXT PRIMARY KEY,
                        primary_email TEXT UNIQUE,
                        display_name TEXT,
                        avatar_url TEXT,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS linked_accounts (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        provider TEXT NOT NULL,
                        provider_account_id TEXT NOT NULL,
                        provider_account_ref TEXT,
                        display_name TEXT,
                        avatar_url TEXT,
                        status TEXT NOT NULL,
                        capabilities_json TEXT NOT NULL,
                        metadata_json TEXT NOT NULL,
                        last_synced_at TIMESTAMPTZ NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL,
                        UNIQUE(provider, provider_account_id)
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS provider_credentials (
                        linked_account_id TEXT PRIMARY KEY,
                        access_token_encrypted TEXT NOT NULL,
                        refresh_token_encrypted TEXT,
                        scope TEXT,
                        expires_at TIMESTAMPTZ NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS oauth_flows (
                        state TEXT PRIMARY KEY,
                        provider TEXT NOT NULL,
                        intent TEXT NOT NULL,
                        user_id TEXT NULL,
                        redirect_to TEXT NOT NULL,
                        pkce_verifier TEXT NULL,
                        requested_scopes_json TEXT NOT NULL,
                        expires_at TIMESTAMPTZ NOT NULL,
                        consumed_at TIMESTAMPTZ NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS app_sessions (
                        session_id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        active_linked_account_id TEXT NULL,
                        session_expires_at TIMESTAMPTZ NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_linked_accounts_user
                    ON linked_accounts (user_id, created_at ASC)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_oauth_flows_expires
                    ON oauth_flows (expires_at)
                    """
                )
            connection.commit()

    @contextmanager
    def _connect(self) -> Generator[psycopg.Connection, None, None]:
        connection = psycopg.connect(self.database_url, row_factory=dict_row)
        try:
            yield connection
        finally:
            connection.close()

    def _pg_row_to_user(self, row: dict[str, Any] | None) -> AppUserRecord | None:
        if row is None:
            return None
        return AppUserRecord(
            id=str(row["id"]),
            primary_email=row["primary_email"],
            display_name=row["display_name"],
            avatar_url=row["avatar_url"],
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
        )

    def _pg_row_to_linked_account(self, row: dict[str, Any]) -> LinkedAccountRecord:
        return LinkedAccountRecord(
            id=str(row["id"]),
            user_id=str(row["user_id"]),
            provider=str(row["provider"]),
            provider_account_id=str(row["provider_account_id"]),
            provider_account_ref=row["provider_account_ref"],
            display_name=row["display_name"],
            avatar_url=row["avatar_url"],
            status=str(row["status"]),
            capabilities=self._load_list(row["capabilities_json"]),
            metadata=self._load_dict(row["metadata_json"]),
            last_synced_at=self._parse_optional_datetime(row["last_synced_at"]),
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
        )

    def _pg_row_to_oauth_flow(self, row: dict[str, Any]) -> OAuthFlowRecord:
        return OAuthFlowRecord(
            state=str(row["state"]),
            provider=str(row["provider"]),
            intent=str(row["intent"]),
            user_id=row["user_id"],
            redirect_to=str(row["redirect_to"]),
            pkce_verifier=row["pkce_verifier"],
            requested_scopes=self._load_list(row["requested_scopes_json"]),
            expires_at=self._parse_datetime(row["expires_at"]),
            consumed_at=self._parse_optional_datetime(row["consumed_at"]),
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
        )

    def _pg_row_to_auth_session(self, row: dict[str, Any]) -> AuthSessionRecord:
        return AuthSessionRecord(
            session_id=str(row["session_id"]),
            user_id=str(row["user_id"]),
            active_linked_account_id=row["active_linked_account_id"],
            provider=str(row["provider"] or "unknown"),
            account_email=row["provider_account_ref"],
            account_name=row["display_name"],
            account_picture=row["avatar_url"],
            access_token=self.cipher.decrypt(row["access_token_encrypted"]) or "",
            refresh_token=self.cipher.decrypt(row["refresh_token_encrypted"]),
            scope=row["scope"],
            expires_at=self._parse_optional_datetime(row["expires_at"]),
            session_expires_at=self._parse_datetime(row["session_expires_at"]),
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
        )


def build_auth_store(
    database_url: str, oauth_state_ttl_seconds: int, encryption_key: str
) -> AuthStore:
    if database_url.startswith("sqlite:///"):
        return SQLiteAuthStore(database_url, oauth_state_ttl_seconds, encryption_key)
    return PostgresAuthStore(database_url, oauth_state_ttl_seconds, encryption_key)
