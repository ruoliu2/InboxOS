from __future__ import annotations

import json
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Protocol
from urllib.parse import unquote, urlparse

import psycopg
from psycopg.rows import dict_row

from app.schemas.thread import MailboxCountsResponse, ThreadSummary, ThreadSummaryPage


@dataclass
class GmailMailboxSyncStateRecord:
    linked_account_id: str
    account_email: str
    history_id: str | None
    watch_expiration: datetime | None
    last_sync_status: str
    last_synced_at: datetime | None
    created_at: datetime
    updated_at: datetime


class GmailMailboxStore(Protocol):
    def clear(self) -> None: ...

    def get_thread_page(
        self,
        linked_account_id: str,
        *,
        mailbox_key: str = "inbox",
        unread_only: bool = False,
        query: str | None = None,
        page_key: str | None = None,
    ) -> ThreadSummaryPage | None: ...

    def store_thread_page(
        self,
        linked_account_id: str,
        *,
        page: ThreadSummaryPage,
        mailbox_key: str = "inbox",
        unread_only: bool = False,
        query: str | None = None,
        page_key: str | None = None,
    ) -> None: ...

    def get_thread_summaries(
        self, linked_account_id: str, thread_ids: list[str]
    ) -> dict[str, ThreadSummary]: ...

    def upsert_thread_summaries(
        self,
        linked_account_id: str,
        summaries: list[ThreadSummary],
        *,
        history_id: str | None = None,
    ) -> None: ...

    def delete_thread_summaries(
        self, linked_account_id: str, thread_ids: list[str]
    ) -> None: ...

    def invalidate_account_pages(self, linked_account_id: str) -> None: ...

    def get_mailbox_counts(
        self, linked_account_id: str
    ) -> MailboxCountsResponse | None: ...

    def upsert_mailbox_counts(
        self,
        linked_account_id: str,
        counts: MailboxCountsResponse,
        *,
        synced_at: datetime | None = None,
    ) -> None: ...

    def get_sync_state(
        self, linked_account_id: str
    ) -> GmailMailboxSyncStateRecord | None: ...

    def get_sync_state_by_account_email(
        self, account_email: str
    ) -> GmailMailboxSyncStateRecord | None: ...

    def upsert_sync_state(self, record: GmailMailboxSyncStateRecord) -> None: ...


class _BaseGmailMailboxStore:
    def __init__(self) -> None:
        self._lock = Lock()

    def _normalize_mailbox(self, mailbox_key: str | None) -> str:
        normalized = (mailbox_key or "inbox").strip().lower()
        return normalized or "inbox"

    def _normalize_query(self, query: str | None) -> str:
        return (query or "").strip()

    def _normalize_page_key(self, page_key: str | None) -> str:
        return (page_key or "").strip()

    def _normalize_unread(self, unread_only: bool) -> int:
        return int(bool(unread_only))

    def _serialize_datetime(self, value: datetime | None) -> str | None:
        return value.isoformat() if value is not None else None

    def _parse_datetime(self, value: str | datetime) -> datetime:
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(value)

    def _parse_optional_datetime(self, value: str | datetime | None) -> datetime | None:
        if value is None:
            return None
        return self._parse_datetime(value)

    def _dump_json(self, value: list[str]) -> str:
        return json.dumps(value)

    def _load_json_list(self, value: str | list[str]) -> list[str]:
        if isinstance(value, list):
            return [str(item) for item in value]
        payload = json.loads(value)
        return [str(item) for item in payload] if isinstance(payload, list) else []

    def _page_to_row_payload(self, page: ThreadSummaryPage) -> tuple[str, int]:
        return (
            json.dumps([thread.id for thread in page.threads]),
            page.hydrated_count,
        )


class SQLiteGmailMailboxStore(_BaseGmailMailboxStore):
    def __init__(self, database_url: str) -> None:
        super().__init__()
        parsed = urlparse(database_url)
        if parsed.scheme != "sqlite":
            raise ValueError(f"Unsupported SQLite database URL: {database_url}")
        raw_path = unquote(parsed.path)
        self.db_path = Path(raw_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def clear(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM gmail_thread_pages")
            connection.execute("DELETE FROM gmail_thread_summaries")
            connection.execute("DELETE FROM gmail_mailbox_counts")
            connection.execute("DELETE FROM gmail_mailbox_sync_state")
            connection.commit()

    def get_thread_page(
        self,
        linked_account_id: str,
        *,
        mailbox_key: str = "inbox",
        unread_only: bool = False,
        query: str | None = None,
        page_key: str | None = None,
    ) -> ThreadSummaryPage | None:
        normalized_mailbox = self._normalize_mailbox(mailbox_key)
        normalized_unread = self._normalize_unread(unread_only)
        normalized_query = self._normalize_query(query)
        normalized_page_key = self._normalize_page_key(page_key)
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT thread_ids_json, next_page_token, has_more, total_count, source, synced_at
                FROM gmail_thread_pages
                WHERE linked_account_id = ? AND mailbox_key = ? AND unread_only = ?
                  AND query = ? AND page_key = ?
                """,
                (
                    linked_account_id,
                    normalized_mailbox,
                    normalized_unread,
                    normalized_query,
                    normalized_page_key,
                ),
            ).fetchone()
            if row is None:
                return None
            thread_ids = self._load_json_list(row["thread_ids_json"])
            summaries = self._get_thread_summaries_with_connection(
                connection, linked_account_id, thread_ids
            )
            threads = [
                summaries.get(thread_id) or {"state": "placeholder", "id": thread_id}
                for thread_id in thread_ids
            ]
            return ThreadSummaryPage(
                threads=threads,
                next_page_token=row["next_page_token"],
                has_more=bool(row["has_more"]),
                total_count=row["total_count"],
                hydrated_count=len(summaries),
                source=str(row["source"] or "cache"),
                synced_at=self._parse_optional_datetime(row["synced_at"]),
            )

    def store_thread_page(
        self,
        linked_account_id: str,
        *,
        page: ThreadSummaryPage,
        mailbox_key: str = "inbox",
        unread_only: bool = False,
        query: str | None = None,
        page_key: str | None = None,
    ) -> None:
        normalized_mailbox = self._normalize_mailbox(mailbox_key)
        normalized_unread = self._normalize_unread(unread_only)
        normalized_query = self._normalize_query(query)
        normalized_page_key = self._normalize_page_key(page_key)
        thread_ids_json, _ = self._page_to_row_payload(page)
        with self._lock, self._connect() as connection:
            for thread in page.threads:
                if not isinstance(thread, ThreadSummary):
                    continue
                self._upsert_summary_row(connection, linked_account_id, thread)
            connection.execute(
                """
                INSERT INTO gmail_thread_pages (
                    linked_account_id, mailbox_key, unread_only, query, page_key,
                    thread_ids_json, next_page_token, has_more, total_count, source,
                    synced_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(linked_account_id, mailbox_key, unread_only, query, page_key)
                DO UPDATE SET
                    thread_ids_json = excluded.thread_ids_json,
                    next_page_token = excluded.next_page_token,
                    has_more = excluded.has_more,
                    total_count = excluded.total_count,
                    source = excluded.source,
                    synced_at = excluded.synced_at,
                    updated_at = excluded.updated_at
                """,
                (
                    linked_account_id,
                    normalized_mailbox,
                    normalized_unread,
                    normalized_query,
                    normalized_page_key,
                    thread_ids_json,
                    page.next_page_token,
                    int(page.has_more),
                    page.total_count,
                    page.source,
                    self._serialize_datetime(page.synced_at),
                    datetime.now(UTC).isoformat(),
                ),
            )
            connection.commit()

    def get_thread_summaries(
        self, linked_account_id: str, thread_ids: list[str]
    ) -> dict[str, ThreadSummary]:
        if not thread_ids:
            return {}
        with self._lock, self._connect() as connection:
            return self._get_thread_summaries_with_connection(
                connection, linked_account_id, thread_ids
            )

    def upsert_thread_summaries(
        self,
        linked_account_id: str,
        summaries: list[ThreadSummary],
        *,
        history_id: str | None = None,
    ) -> None:
        with self._lock, self._connect() as connection:
            for summary in summaries:
                self._upsert_summary_row(
                    connection, linked_account_id, summary, history_id
                )
            connection.commit()

    def delete_thread_summaries(
        self, linked_account_id: str, thread_ids: list[str]
    ) -> None:
        if not thread_ids:
            return
        with self._lock, self._connect() as connection:
            connection.execute(
                f"""
                DELETE FROM gmail_thread_summaries
                WHERE linked_account_id = ? AND thread_id IN ({",".join("?" for _ in thread_ids)})
                """,
                (linked_account_id, *thread_ids),
            )
            connection.commit()

    def invalidate_account_pages(self, linked_account_id: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM gmail_thread_pages WHERE linked_account_id = ?",
                (linked_account_id,),
            )
            connection.commit()

    def get_mailbox_counts(
        self, linked_account_id: str
    ) -> MailboxCountsResponse | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT inbox, sent, archive, trash, junk
                FROM gmail_mailbox_counts
                WHERE linked_account_id = ?
                """,
                (linked_account_id,),
            ).fetchone()
        if row is None:
            return None
        return MailboxCountsResponse(
            inbox=row["inbox"],
            sent=row["sent"],
            archive=row["archive"],
            trash=row["trash"],
            junk=row["junk"],
        )

    def upsert_mailbox_counts(
        self,
        linked_account_id: str,
        counts: MailboxCountsResponse,
        *,
        synced_at: datetime | None = None,
    ) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO gmail_mailbox_counts (
                    linked_account_id, inbox, sent, archive, trash, junk, synced_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(linked_account_id) DO UPDATE SET
                    inbox = excluded.inbox,
                    sent = excluded.sent,
                    archive = excluded.archive,
                    trash = excluded.trash,
                    junk = excluded.junk,
                    synced_at = excluded.synced_at,
                    updated_at = excluded.updated_at
                """,
                (
                    linked_account_id,
                    counts.inbox,
                    counts.sent,
                    counts.archive,
                    counts.trash,
                    counts.junk,
                    self._serialize_datetime(synced_at),
                    datetime.now(UTC).isoformat(),
                ),
            )
            connection.commit()

    def get_sync_state(
        self, linked_account_id: str
    ) -> GmailMailboxSyncStateRecord | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT linked_account_id, account_email, history_id, watch_expiration,
                       last_sync_status, last_synced_at, created_at, updated_at
                FROM gmail_mailbox_sync_state
                WHERE linked_account_id = ?
                """,
                (linked_account_id,),
            ).fetchone()
        return self._row_to_sync_state(row) if row is not None else None

    def get_sync_state_by_account_email(
        self, account_email: str
    ) -> GmailMailboxSyncStateRecord | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT linked_account_id, account_email, history_id, watch_expiration,
                       last_sync_status, last_synced_at, created_at, updated_at
                FROM gmail_mailbox_sync_state
                WHERE account_email = ?
                """,
                (account_email.strip().lower(),),
            ).fetchone()
        return self._row_to_sync_state(row) if row is not None else None

    def upsert_sync_state(self, record: GmailMailboxSyncStateRecord) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO gmail_mailbox_sync_state (
                    linked_account_id, account_email, history_id, watch_expiration,
                    last_sync_status, last_synced_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(linked_account_id) DO UPDATE SET
                    account_email = excluded.account_email,
                    history_id = excluded.history_id,
                    watch_expiration = excluded.watch_expiration,
                    last_sync_status = excluded.last_sync_status,
                    last_synced_at = excluded.last_synced_at,
                    updated_at = excluded.updated_at
                """,
                (
                    record.linked_account_id,
                    record.account_email.strip().lower(),
                    record.history_id,
                    self._serialize_datetime(record.watch_expiration),
                    record.last_sync_status,
                    self._serialize_datetime(record.last_synced_at),
                    record.created_at.isoformat(),
                    record.updated_at.isoformat(),
                ),
            )
            connection.commit()

    def _upsert_summary_row(
        self,
        connection: sqlite3.Connection,
        linked_account_id: str,
        summary: ThreadSummary,
        history_id: str | None = None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO gmail_thread_summaries (
                linked_account_id, thread_id, subject, snippet, participants_json,
                last_message_at, action_states_json, history_id, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(linked_account_id, thread_id) DO UPDATE SET
                subject = excluded.subject,
                snippet = excluded.snippet,
                participants_json = excluded.participants_json,
                last_message_at = excluded.last_message_at,
                action_states_json = excluded.action_states_json,
                history_id = COALESCE(excluded.history_id, gmail_thread_summaries.history_id),
                updated_at = excluded.updated_at
            """,
            (
                linked_account_id,
                summary.id,
                summary.subject,
                summary.snippet,
                json.dumps(summary.participants),
                summary.last_message_at.isoformat(),
                json.dumps(summary.action_states),
                history_id,
                datetime.now(UTC).isoformat(),
            ),
        )

    def _get_thread_summaries_with_connection(
        self,
        connection: sqlite3.Connection,
        linked_account_id: str,
        thread_ids: list[str],
    ) -> dict[str, ThreadSummary]:
        if not thread_ids:
            return {}
        rows = connection.execute(
            f"""
            SELECT thread_id, subject, snippet, participants_json, last_message_at,
                   action_states_json
            FROM gmail_thread_summaries
            WHERE linked_account_id = ? AND thread_id IN ({",".join("?" for _ in thread_ids)})
            """,
            (linked_account_id, *thread_ids),
        ).fetchall()
        return {
            str(row["thread_id"]): ThreadSummary(
                id=str(row["thread_id"]),
                subject=str(row["subject"]),
                snippet=str(row["snippet"]),
                participants=self._load_json_list(row["participants_json"]),
                last_message_at=self._parse_datetime(row["last_message_at"]),
                action_states=self._load_json_list(row["action_states_json"]),  # type: ignore[arg-type]
            )
            for row in rows
        }

    def _row_to_sync_state(self, row: sqlite3.Row) -> GmailMailboxSyncStateRecord:
        return GmailMailboxSyncStateRecord(
            linked_account_id=str(row["linked_account_id"]),
            account_email=str(row["account_email"]),
            history_id=row["history_id"],
            watch_expiration=self._parse_optional_datetime(row["watch_expiration"]),
            last_sync_status=str(row["last_sync_status"] or "idle"),
            last_synced_at=self._parse_optional_datetime(row["last_synced_at"]),
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
        )

    def _init_db(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS gmail_thread_summaries (
                    linked_account_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    snippet TEXT NOT NULL,
                    participants_json TEXT NOT NULL,
                    last_message_at TEXT NOT NULL,
                    action_states_json TEXT NOT NULL,
                    history_id TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (linked_account_id, thread_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS gmail_thread_pages (
                    linked_account_id TEXT NOT NULL,
                    mailbox_key TEXT NOT NULL,
                    unread_only INTEGER NOT NULL,
                    query TEXT NOT NULL,
                    page_key TEXT NOT NULL,
                    thread_ids_json TEXT NOT NULL,
                    next_page_token TEXT,
                    has_more INTEGER NOT NULL,
                    total_count INTEGER,
                    source TEXT NOT NULL,
                    synced_at TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (
                        linked_account_id,
                        mailbox_key,
                        unread_only,
                        query,
                        page_key
                    )
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS gmail_mailbox_counts (
                    linked_account_id TEXT PRIMARY KEY,
                    inbox INTEGER,
                    sent INTEGER,
                    archive INTEGER,
                    trash INTEGER,
                    junk INTEGER,
                    synced_at TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS gmail_mailbox_sync_state (
                    linked_account_id TEXT PRIMARY KEY,
                    account_email TEXT NOT NULL UNIQUE,
                    history_id TEXT,
                    watch_expiration TEXT,
                    last_sync_status TEXT NOT NULL,
                    last_synced_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.commit()

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()


class PostgresGmailMailboxStore(_BaseGmailMailboxStore):
    def __init__(self, database_url: str) -> None:
        super().__init__()
        self.database_url = database_url
        self._init_db()

    def clear(self) -> None:
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM gmail_thread_pages")
                cursor.execute("DELETE FROM gmail_thread_summaries")
                cursor.execute("DELETE FROM gmail_mailbox_counts")
                cursor.execute("DELETE FROM gmail_mailbox_sync_state")
            connection.commit()

    def get_thread_page(
        self,
        linked_account_id: str,
        *,
        mailbox_key: str = "inbox",
        unread_only: bool = False,
        query: str | None = None,
        page_key: str | None = None,
    ) -> ThreadSummaryPage | None:
        normalized_mailbox = self._normalize_mailbox(mailbox_key)
        normalized_unread = self._normalize_unread(unread_only)
        normalized_query = self._normalize_query(query)
        normalized_page_key = self._normalize_page_key(page_key)
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        thread_ids_json,
                        next_page_token,
                        has_more,
                        total_count,
                        source,
                        synced_at
                    FROM gmail_thread_pages
                    WHERE linked_account_id = %s AND mailbox_key = %s AND unread_only = %s
                      AND query = %s AND page_key = %s
                    """,
                    (
                        linked_account_id,
                        normalized_mailbox,
                        normalized_unread,
                        normalized_query,
                        normalized_page_key,
                    ),
                )
                row = cursor.fetchone()
        if row is None:
            return None
        thread_ids = self._load_json_list(row["thread_ids_json"])
        summaries = self.get_thread_summaries(linked_account_id, thread_ids)
        threads = [
            summaries.get(thread_id) or {"state": "placeholder", "id": thread_id}
            for thread_id in thread_ids
        ]
        return ThreadSummaryPage(
            threads=threads,
            next_page_token=row["next_page_token"],
            has_more=bool(row["has_more"]),
            total_count=row["total_count"],
            hydrated_count=len(summaries),
            source=str(row["source"] or "cache"),
            synced_at=self._parse_optional_datetime(row["synced_at"]),
        )

    def store_thread_page(
        self,
        linked_account_id: str,
        *,
        page: ThreadSummaryPage,
        mailbox_key: str = "inbox",
        unread_only: bool = False,
        query: str | None = None,
        page_key: str | None = None,
    ) -> None:
        normalized_mailbox = self._normalize_mailbox(mailbox_key)
        normalized_unread = self._normalize_unread(unread_only)
        normalized_query = self._normalize_query(query)
        normalized_page_key = self._normalize_page_key(page_key)
        thread_ids_json, _ = self._page_to_row_payload(page)
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                for thread in page.threads:
                    if not isinstance(thread, ThreadSummary):
                        continue
                    self._upsert_summary_row(cursor, linked_account_id, thread)
                cursor.execute(
                    """
                    INSERT INTO gmail_thread_pages (
                        linked_account_id, mailbox_key, unread_only, query, page_key,
                        thread_ids_json, next_page_token, has_more, total_count, source,
                        synced_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (linked_account_id, mailbox_key, unread_only, query, page_key)
                    DO UPDATE SET
                        thread_ids_json = excluded.thread_ids_json,
                        next_page_token = excluded.next_page_token,
                        has_more = excluded.has_more,
                        total_count = excluded.total_count,
                        source = excluded.source,
                        synced_at = excluded.synced_at,
                        updated_at = excluded.updated_at
                    """,
                    (
                        linked_account_id,
                        normalized_mailbox,
                        normalized_unread,
                        normalized_query,
                        normalized_page_key,
                        thread_ids_json,
                        page.next_page_token,
                        page.has_more,
                        page.total_count,
                        page.source,
                        page.synced_at,
                        datetime.now(UTC),
                    ),
                )
            connection.commit()

    def get_thread_summaries(
        self, linked_account_id: str, thread_ids: list[str]
    ) -> dict[str, ThreadSummary]:
        if not thread_ids:
            return {}
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT thread_id, subject, snippet, participants_json, last_message_at,
                           action_states_json
                    FROM gmail_thread_summaries
                    WHERE linked_account_id = %s AND thread_id = ANY(%s)
                    """,
                    (linked_account_id, thread_ids),
                )
                rows = cursor.fetchall()
        return {
            str(row["thread_id"]): ThreadSummary(
                id=str(row["thread_id"]),
                subject=str(row["subject"]),
                snippet=str(row["snippet"]),
                participants=self._load_json_list(row["participants_json"]),
                last_message_at=self._parse_datetime(row["last_message_at"]),
                action_states=self._load_json_list(row["action_states_json"]),  # type: ignore[arg-type]
            )
            for row in rows
        }

    def upsert_thread_summaries(
        self,
        linked_account_id: str,
        summaries: list[ThreadSummary],
        *,
        history_id: str | None = None,
    ) -> None:
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                for summary in summaries:
                    self._upsert_summary_row(
                        cursor, linked_account_id, summary, history_id
                    )
            connection.commit()

    def delete_thread_summaries(
        self, linked_account_id: str, thread_ids: list[str]
    ) -> None:
        if not thread_ids:
            return
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM gmail_thread_summaries
                    WHERE linked_account_id = %s AND thread_id = ANY(%s)
                    """,
                    (linked_account_id, thread_ids),
                )
            connection.commit()

    def invalidate_account_pages(self, linked_account_id: str) -> None:
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM gmail_thread_pages WHERE linked_account_id = %s",
                    (linked_account_id,),
                )
            connection.commit()

    def get_mailbox_counts(
        self, linked_account_id: str
    ) -> MailboxCountsResponse | None:
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT inbox, sent, archive, trash, junk
                    FROM gmail_mailbox_counts
                    WHERE linked_account_id = %s
                    """,
                    (linked_account_id,),
                )
                row = cursor.fetchone()
        if row is None:
            return None
        return MailboxCountsResponse(
            inbox=row["inbox"],
            sent=row["sent"],
            archive=row["archive"],
            trash=row["trash"],
            junk=row["junk"],
        )

    def upsert_mailbox_counts(
        self,
        linked_account_id: str,
        counts: MailboxCountsResponse,
        *,
        synced_at: datetime | None = None,
    ) -> None:
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO gmail_mailbox_counts (
                        linked_account_id, inbox, sent, archive, trash, junk, synced_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (linked_account_id) DO UPDATE SET
                        inbox = excluded.inbox,
                        sent = excluded.sent,
                        archive = excluded.archive,
                        trash = excluded.trash,
                        junk = excluded.junk,
                        synced_at = excluded.synced_at,
                        updated_at = excluded.updated_at
                    """,
                    (
                        linked_account_id,
                        counts.inbox,
                        counts.sent,
                        counts.archive,
                        counts.trash,
                        counts.junk,
                        synced_at,
                        datetime.now(UTC),
                    ),
                )
            connection.commit()

    def get_sync_state(
        self, linked_account_id: str
    ) -> GmailMailboxSyncStateRecord | None:
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT linked_account_id, account_email, history_id, watch_expiration,
                           last_sync_status, last_synced_at, created_at, updated_at
                    FROM gmail_mailbox_sync_state
                    WHERE linked_account_id = %s
                    """,
                    (linked_account_id,),
                )
                row = cursor.fetchone()
        return self._row_to_sync_state(row) if row is not None else None

    def get_sync_state_by_account_email(
        self, account_email: str
    ) -> GmailMailboxSyncStateRecord | None:
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT linked_account_id, account_email, history_id, watch_expiration,
                           last_sync_status, last_synced_at, created_at, updated_at
                    FROM gmail_mailbox_sync_state
                    WHERE account_email = %s
                    """,
                    (account_email.strip().lower(),),
                )
                row = cursor.fetchone()
        return self._row_to_sync_state(row) if row is not None else None

    def upsert_sync_state(self, record: GmailMailboxSyncStateRecord) -> None:
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO gmail_mailbox_sync_state (
                        linked_account_id, account_email, history_id, watch_expiration,
                        last_sync_status, last_synced_at, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (linked_account_id) DO UPDATE SET
                        account_email = excluded.account_email,
                        history_id = excluded.history_id,
                        watch_expiration = excluded.watch_expiration,
                        last_sync_status = excluded.last_sync_status,
                        last_synced_at = excluded.last_synced_at,
                        updated_at = excluded.updated_at
                    """,
                    (
                        record.linked_account_id,
                        record.account_email.strip().lower(),
                        record.history_id,
                        record.watch_expiration,
                        record.last_sync_status,
                        record.last_synced_at,
                        record.created_at,
                        record.updated_at,
                    ),
                )
            connection.commit()

    def _upsert_summary_row(
        self,
        cursor: psycopg.Cursor,
        linked_account_id: str,
        summary: ThreadSummary,
        history_id: str | None = None,
    ) -> None:
        cursor.execute(
            """
            INSERT INTO gmail_thread_summaries (
                linked_account_id, thread_id, subject, snippet, participants_json,
                last_message_at, action_states_json, history_id, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (linked_account_id, thread_id) DO UPDATE SET
                subject = excluded.subject,
                snippet = excluded.snippet,
                participants_json = excluded.participants_json,
                last_message_at = excluded.last_message_at,
                action_states_json = excluded.action_states_json,
                history_id = COALESCE(excluded.history_id, gmail_thread_summaries.history_id),
                updated_at = excluded.updated_at
            """,
            (
                linked_account_id,
                summary.id,
                summary.subject,
                summary.snippet,
                json.dumps(summary.participants),
                summary.last_message_at,
                json.dumps(summary.action_states),
                history_id,
                datetime.now(UTC),
            ),
        )

    def _row_to_sync_state(self, row: dict[str, object]) -> GmailMailboxSyncStateRecord:
        return GmailMailboxSyncStateRecord(
            linked_account_id=str(row["linked_account_id"]),
            account_email=str(row["account_email"]),
            history_id=(
                str(row["history_id"]) if row["history_id"] is not None else None
            ),
            watch_expiration=self._parse_optional_datetime(row["watch_expiration"]),  # type: ignore[arg-type]
            last_sync_status=str(row["last_sync_status"] or "idle"),
            last_synced_at=self._parse_optional_datetime(row["last_synced_at"]),  # type: ignore[arg-type]
            created_at=self._parse_datetime(row["created_at"]),  # type: ignore[arg-type]
            updated_at=self._parse_datetime(row["updated_at"]),  # type: ignore[arg-type]
        )

    def _init_db(self) -> None:
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS gmail_thread_summaries (
                        linked_account_id TEXT NOT NULL,
                        thread_id TEXT NOT NULL,
                        subject TEXT NOT NULL,
                        snippet TEXT NOT NULL,
                        participants_json TEXT NOT NULL,
                        last_message_at TIMESTAMPTZ NOT NULL,
                        action_states_json TEXT NOT NULL,
                        history_id TEXT NULL,
                        updated_at TIMESTAMPTZ NOT NULL,
                        PRIMARY KEY (linked_account_id, thread_id)
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS gmail_thread_pages (
                        linked_account_id TEXT NOT NULL,
                        mailbox_key TEXT NOT NULL,
                        unread_only INTEGER NOT NULL,
                        query TEXT NOT NULL,
                        page_key TEXT NOT NULL,
                        thread_ids_json TEXT NOT NULL,
                        next_page_token TEXT NULL,
                        has_more BOOLEAN NOT NULL,
                        total_count INTEGER NULL,
                        source TEXT NOT NULL,
                        synced_at TIMESTAMPTZ NULL,
                        updated_at TIMESTAMPTZ NOT NULL,
                        PRIMARY KEY (
                            linked_account_id,
                            mailbox_key,
                            unread_only,
                            query,
                            page_key
                        )
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS gmail_mailbox_counts (
                        linked_account_id TEXT PRIMARY KEY,
                        inbox INTEGER NULL,
                        sent INTEGER NULL,
                        archive INTEGER NULL,
                        trash INTEGER NULL,
                        junk INTEGER NULL,
                        synced_at TIMESTAMPTZ NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS gmail_mailbox_sync_state (
                        linked_account_id TEXT PRIMARY KEY,
                        account_email TEXT NOT NULL UNIQUE,
                        history_id TEXT NULL,
                        watch_expiration TIMESTAMPTZ NULL,
                        last_sync_status TEXT NOT NULL,
                        last_synced_at TIMESTAMPTZ NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
            connection.commit()

    @contextmanager
    def _connect(self) -> Generator[psycopg.Connection, None, None]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            yield connection


def build_gmail_mailbox_store(database_url: str) -> GmailMailboxStore:
    if database_url.startswith("sqlite:///"):
        return SQLiteGmailMailboxStore(database_url)
    return PostgresGmailMailboxStore(database_url)
