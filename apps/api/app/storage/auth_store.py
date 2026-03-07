from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock


@dataclass
class OAuthStateRecord:
    state: str
    redirect_to: str
    created_at: datetime


@dataclass
class AuthSessionRecord:
    session_id: str
    provider: str
    account_email: str
    account_name: str | None
    account_picture: str | None
    access_token: str
    refresh_token: str | None
    scope: str | None
    expires_at: datetime | None
    session_expires_at: datetime
    created_at: datetime
    updated_at: datetime


class SQLiteAuthStore:
    def __init__(self, db_path: str, oauth_state_ttl_seconds: int) -> None:
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.oauth_state_ttl = timedelta(seconds=oauth_state_ttl_seconds)
        self._lock = Lock()
        self._init_db()

    def clear(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM auth_sessions")
            connection.execute("DELETE FROM oauth_states")
            connection.commit()

    def save_oauth_state(self, state: OAuthStateRecord) -> None:
        with self._lock, self._connect() as connection:
            self._delete_expired_oauth_states(connection)
            connection.execute(
                """
                INSERT INTO oauth_states (
                    state,
                    redirect_to,
                    created_at
                ) VALUES (?, ?, ?)
                ON CONFLICT(state) DO UPDATE SET
                    redirect_to = excluded.redirect_to,
                    created_at = excluded.created_at
                """,
                (
                    state.state,
                    state.redirect_to,
                    state.created_at.isoformat(),
                ),
            )
            connection.commit()

    def pop_oauth_state(self, state: str) -> OAuthStateRecord | None:
        cutoff = datetime.now(UTC) - self.oauth_state_ttl
        with self._lock, self._connect() as connection:
            self._delete_expired_oauth_states(connection, cutoff=cutoff)
            row = connection.execute(
                """
                SELECT state, redirect_to, created_at
                FROM oauth_states
                WHERE state = ?
                """,
                (state,),
            ).fetchone()
            connection.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
            connection.commit()

        if row is None:
            return None

        record = OAuthStateRecord(
            state=row["state"],
            redirect_to=row["redirect_to"],
            created_at=self._parse_datetime(row["created_at"]),
        )
        if record.created_at <= cutoff:
            return None
        return record

    def upsert_session(self, session: AuthSessionRecord) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO auth_sessions (
                    session_id,
                    provider,
                    account_email,
                    account_name,
                    account_picture,
                    access_token,
                    refresh_token,
                    scope,
                    expires_at,
                    session_expires_at,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    provider = excluded.provider,
                    account_email = excluded.account_email,
                    account_name = excluded.account_name,
                    account_picture = excluded.account_picture,
                    access_token = excluded.access_token,
                    refresh_token = excluded.refresh_token,
                    scope = excluded.scope,
                    expires_at = excluded.expires_at,
                    session_expires_at = excluded.session_expires_at,
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at
                """,
                (
                    session.session_id,
                    session.provider,
                    session.account_email,
                    session.account_name,
                    session.account_picture,
                    session.access_token,
                    session.refresh_token,
                    session.scope,
                    self._serialize_datetime(session.expires_at),
                    session.session_expires_at.isoformat(),
                    session.created_at.isoformat(),
                    session.updated_at.isoformat(),
                ),
            )
            connection.commit()

    def get_session(self, session_id: str) -> AuthSessionRecord | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT session_id, provider, account_email, account_name,
                       account_picture, access_token, refresh_token, scope,
                       expires_at, session_expires_at, created_at, updated_at
                FROM auth_sessions
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()

        if row is None:
            return None
        return AuthSessionRecord(
            session_id=row["session_id"],
            provider=row["provider"],
            account_email=row["account_email"],
            account_name=row["account_name"],
            account_picture=row["account_picture"],
            access_token=row["access_token"],
            refresh_token=row["refresh_token"],
            scope=row["scope"],
            expires_at=self._parse_optional_datetime(row["expires_at"]),
            session_expires_at=self._parse_datetime(row["session_expires_at"]),
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
        )

    def delete_session(self, session_id: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM auth_sessions WHERE session_id = ?",
                (session_id,),
            )
            connection.commit()

    def _init_db(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    session_id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    account_email TEXT NOT NULL,
                    account_name TEXT,
                    account_picture TEXT,
                    access_token TEXT NOT NULL,
                    refresh_token TEXT,
                    scope TEXT,
                    expires_at TEXT,
                    session_expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS oauth_states (
                    state TEXT PRIMARY KEY,
                    redirect_to TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.commit()

    def _delete_expired_oauth_states(
        self,
        connection: sqlite3.Connection,
        *,
        cutoff: datetime | None = None,
    ) -> None:
        effective_cutoff = cutoff or (datetime.now(UTC) - self.oauth_state_ttl)
        connection.execute(
            "DELETE FROM oauth_states WHERE created_at <= ?",
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

    def _serialize_datetime(self, value: datetime | None) -> str | None:
        return value.isoformat() if value is not None else None

    def _parse_optional_datetime(self, value: str | None) -> datetime | None:
        return self._parse_datetime(value) if value else None

    def _parse_datetime(self, value: str) -> datetime:
        return datetime.fromisoformat(value)
