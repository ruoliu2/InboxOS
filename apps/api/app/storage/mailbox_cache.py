from __future__ import annotations

import json
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

from app.schemas.thread import ThreadDetail, ThreadSummary, ThreadSummaryPage


class GmailMailboxCache:
    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._init_db()

    def clear(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM gmail_thread_pages")
            connection.execute("DELETE FROM gmail_thread_details")
            connection.execute("DELETE FROM gmail_thread_summaries")
            connection.commit()

    def get_thread_page(
        self,
        account_email: str,
        *,
        query: str | None = None,
        page_key: str | None = None,
    ) -> ThreadSummaryPage | None:
        normalized_query = self._normalize_query(query)
        normalized_page_key = self._normalize_page_key(page_key)

        with self._lock, self._connect() as connection:
            page_row = connection.execute(
                """
                SELECT thread_ids_json, next_page_token, has_more
                FROM gmail_thread_pages
                WHERE account_email = ? AND query = ? AND page_key = ?
                """,
                (account_email, normalized_query, normalized_page_key),
            ).fetchone()

            if page_row is None:
                return None

            thread_ids = json.loads(page_row["thread_ids_json"])
            if not isinstance(thread_ids, list) or not thread_ids:
                return None

            summaries_by_id: dict[str, ThreadSummary] = {}
            summary_rows = connection.execute(
                f"""
                SELECT thread_id, subject, snippet, participants_json, last_message_at,
                       action_states_json
                FROM gmail_thread_summaries
                WHERE account_email = ? AND thread_id IN ({",".join("?" for _ in thread_ids)})
                """,
                (account_email, *thread_ids),
            ).fetchall()
            for row in summary_rows:
                summary = self._row_to_summary(row)
                summaries_by_id[summary.id] = summary

            ordered_threads: list[ThreadSummary] = []
            for thread_id in thread_ids:
                summary = summaries_by_id.get(thread_id)
                if summary is None:
                    return None
                ordered_threads.append(summary)

            return ThreadSummaryPage(
                threads=ordered_threads,
                next_page_token=page_row["next_page_token"],
                has_more=bool(page_row["has_more"]),
            )

    def store_thread_page(
        self,
        account_email: str,
        *,
        page: ThreadSummaryPage,
        query: str | None = None,
        page_key: str | None = None,
    ) -> None:
        normalized_query = self._normalize_query(query)
        normalized_page_key = self._normalize_page_key(page_key)
        updated_at = datetime.now(UTC).isoformat()

        with self._lock, self._connect() as connection:
            for thread in page.threads:
                connection.execute(
                    """
                    INSERT INTO gmail_thread_summaries (
                        account_email,
                        thread_id,
                        subject,
                        snippet,
                        participants_json,
                        last_message_at,
                        action_states_json,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(account_email, thread_id) DO UPDATE SET
                        subject = excluded.subject,
                        snippet = excluded.snippet,
                        participants_json = excluded.participants_json,
                        last_message_at = excluded.last_message_at,
                        action_states_json = excluded.action_states_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        account_email,
                        thread.id,
                        thread.subject,
                        thread.snippet,
                        json.dumps(thread.participants),
                        thread.last_message_at.isoformat(),
                        json.dumps(thread.action_states),
                        updated_at,
                    ),
                )

            connection.execute(
                """
                INSERT INTO gmail_thread_pages (
                    account_email,
                    query,
                    page_key,
                    thread_ids_json,
                    next_page_token,
                    has_more,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_email, query, page_key) DO UPDATE SET
                    thread_ids_json = excluded.thread_ids_json,
                    next_page_token = excluded.next_page_token,
                    has_more = excluded.has_more,
                    updated_at = excluded.updated_at
                """,
                (
                    account_email,
                    normalized_query,
                    normalized_page_key,
                    json.dumps([thread.id for thread in page.threads]),
                    page.next_page_token,
                    int(page.has_more),
                    updated_at,
                ),
            )
            connection.commit()

    def get_thread_detail(
        self, account_email: str, thread_id: str
    ) -> ThreadDetail | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json
                FROM gmail_thread_details
                WHERE account_email = ? AND thread_id = ?
                """,
                (account_email, thread_id),
            ).fetchone()
            if row is None:
                return None
            return ThreadDetail.model_validate_json(row["payload_json"])

    def upsert_thread_detail(self, account_email: str, thread: ThreadDetail) -> None:
        updated_at = datetime.now(UTC).isoformat()
        summary = ThreadSummary(
            id=thread.id,
            subject=thread.subject,
            snippet=thread.snippet,
            participants=thread.participants,
            last_message_at=thread.last_message_at,
            action_states=thread.action_states,
        )

        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO gmail_thread_details (
                    account_email,
                    thread_id,
                    payload_json,
                    updated_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(account_email, thread_id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    account_email,
                    thread.id,
                    thread.model_dump_json(),
                    updated_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO gmail_thread_summaries (
                    account_email,
                    thread_id,
                    subject,
                    snippet,
                    participants_json,
                    last_message_at,
                    action_states_json,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_email, thread_id) DO UPDATE SET
                    subject = excluded.subject,
                    snippet = excluded.snippet,
                    participants_json = excluded.participants_json,
                    last_message_at = excluded.last_message_at,
                    action_states_json = excluded.action_states_json,
                    updated_at = excluded.updated_at
                """,
                (
                    account_email,
                    summary.id,
                    summary.subject,
                    summary.snippet,
                    json.dumps(summary.participants),
                    summary.last_message_at.isoformat(),
                    json.dumps(summary.action_states),
                    updated_at,
                ),
            )
            connection.commit()

    def _init_db(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS gmail_thread_summaries (
                    account_email TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    snippet TEXT NOT NULL,
                    participants_json TEXT NOT NULL,
                    last_message_at TEXT NOT NULL,
                    action_states_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (account_email, thread_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS gmail_thread_pages (
                    account_email TEXT NOT NULL,
                    query TEXT NOT NULL,
                    page_key TEXT NOT NULL,
                    thread_ids_json TEXT NOT NULL,
                    next_page_token TEXT,
                    has_more INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (account_email, query, page_key)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS gmail_thread_details (
                    account_email TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (account_email, thread_id)
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

    def _normalize_query(self, query: str | None) -> str:
        return (query or "").strip()

    def _normalize_page_key(self, page_key: str | None) -> str:
        return page_key or "__first__"

    def _row_to_summary(self, row: sqlite3.Row) -> ThreadSummary:
        return ThreadSummary(
            id=row["thread_id"],
            subject=row["subject"],
            snippet=row["snippet"],
            participants=json.loads(row["participants_json"]),
            last_message_at=datetime.fromisoformat(row["last_message_at"]),
            action_states=json.loads(row["action_states_json"]),
        )
