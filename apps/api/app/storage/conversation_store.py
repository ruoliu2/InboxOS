from __future__ import annotations

import json
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any, Protocol
from urllib.parse import unquote, urlparse

import psycopg
from psycopg.rows import dict_row

from app.schemas.common import ActionState
from app.schemas.thread import (
    ExtractedDeadline,
    ExtractedTask,
    ThreadAnalysis,
    ThreadDetail,
    ThreadSummary,
)
from app.services.id_factory import new_id


@dataclass
class ConversationRecord:
    id: str
    user_id: str
    linked_account_id: str
    provider: str
    external_conversation_id: str
    title: str
    preview: str
    last_message_at: datetime
    source_folder: str | None
    status: str
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


@dataclass
class ConversationInsightRecord:
    conversation_id: str
    summary: str | None
    action_items: list[str]
    deadlines: list[ExtractedDeadline]
    extracted_tasks: list[ExtractedTask]
    requested_items: list[str]
    recommended_next_action: str | None
    action_states: list[str]
    analyzed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ConversationStore(Protocol):
    def clear(self) -> None: ...

    def upsert_conversation(
        self, conversation: ConversationRecord
    ) -> ConversationRecord: ...

    def get_by_external_id(
        self, user_id: str, linked_account_id: str, external_conversation_id: str
    ) -> ConversationRecord | None: ...

    def get_conversation_by_external_id(
        self, user_id: str, linked_account_id: str, external_conversation_id: str
    ) -> ConversationRecord | None: ...

    def get_conversation(self, conversation_id: str) -> ConversationRecord | None: ...

    def get_external_id(self, conversation_id: str) -> str | None: ...

    def get_insight(self, conversation_id: str) -> ConversationInsightRecord | None: ...

    def get_insight_by_external_id(
        self, user_id: str, linked_account_id: str, external_conversation_id: str
    ) -> ConversationInsightRecord | None: ...

    def list_thread_summaries_by_action_state(
        self,
        user_id: str,
        linked_account_id: str,
        action_state: str,
        *,
        limit: int,
        query: str | None = None,
    ) -> list[ThreadSummary]: ...

    def count_action_states(
        self, user_id: str, linked_account_id: str
    ) -> dict[str, int]: ...

    def upsert_insight(self, insight: ConversationInsightRecord) -> None: ...


class _BaseConversationStore:
    def __init__(self) -> None:
        self._lock = Lock()

    def _dump_json(self, value: object) -> str:
        if isinstance(value, list):
            items: list[object] = []
            for item in value:
                if hasattr(item, "model_dump"):
                    items.append(item.model_dump(mode="json"))
                else:
                    items.append(item)
            return json.dumps(items)
        if hasattr(value, "model_dump"):
            return json.dumps(value.model_dump(mode="json"))
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

    def _load_deadlines(
        self, value: str | list[dict[str, Any]] | list[str] | None
    ) -> list[ExtractedDeadline]:
        if value is None:
            return []
        payload = value if isinstance(value, list) else json.loads(value)
        results: list[ExtractedDeadline] = []
        if not isinstance(payload, list):
            return results
        for item in payload:
            if isinstance(item, str):
                continue
            if isinstance(item, dict):
                results.append(ExtractedDeadline.model_validate(item))
        return results

    def _load_extracted_tasks(
        self, value: str | list[dict[str, Any]] | None
    ) -> list[ExtractedTask]:
        if value is None:
            return []
        payload = value if isinstance(value, list) else json.loads(value)
        results: list[ExtractedTask] = []
        if not isinstance(payload, list):
            return results
        for item in payload:
            if isinstance(item, dict):
                results.append(ExtractedTask.model_validate(item))
        return results

    def _parse_datetime(self, value: str | datetime) -> datetime:
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(value)

    def _parse_optional_datetime(self, value: str | datetime | None) -> datetime | None:
        if value is None:
            return None
        return self._parse_datetime(value)

    def _serialize_datetime(self, value: datetime | None) -> str | None:
        return value.isoformat() if value is not None else None


class SQLiteConversationStore(_BaseConversationStore):
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
            connection.execute("DELETE FROM conversation_insights")
            connection.execute("DELETE FROM conversations")
            connection.commit()

    def upsert_conversation(
        self, conversation: ConversationRecord
    ) -> ConversationRecord:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO conversations (
                    id,
                    user_id,
                    linked_account_id,
                    provider,
                    external_conversation_id,
                    title,
                    preview,
                    last_message_at,
                    source_folder,
                    status,
                    metadata_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(linked_account_id, external_conversation_id) DO UPDATE SET
                    title = excluded.title,
                    preview = excluded.preview,
                    last_message_at = excluded.last_message_at,
                    source_folder = excluded.source_folder,
                    status = excluded.status,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    conversation.id,
                    conversation.user_id,
                    conversation.linked_account_id,
                    conversation.provider,
                    conversation.external_conversation_id,
                    conversation.title,
                    conversation.preview,
                    conversation.last_message_at.isoformat(),
                    conversation.source_folder,
                    conversation.status,
                    self._dump_json(conversation.metadata),
                    conversation.created_at.isoformat(),
                    conversation.updated_at.isoformat(),
                ),
            )
            connection.commit()
            row = connection.execute(
                """
                SELECT id, user_id, linked_account_id, provider, external_conversation_id,
                       title, preview, last_message_at, source_folder, status, metadata_json,
                       created_at, updated_at
                FROM conversations
                WHERE linked_account_id = ? AND external_conversation_id = ?
                """,
                (conversation.linked_account_id, conversation.external_conversation_id),
            ).fetchone()
        if row is None:
            raise RuntimeError("Failed to persist conversation.")
        return self._row_to_conversation(row)

    def get_conversation_by_external_id(
        self, user_id: str, linked_account_id: str, external_conversation_id: str
    ) -> ConversationRecord | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, user_id, linked_account_id, provider, external_conversation_id,
                       title, preview, last_message_at, source_folder, status, metadata_json,
                       created_at, updated_at
                FROM conversations
                WHERE user_id = ? AND linked_account_id = ? AND external_conversation_id = ?
                """,
                (user_id, linked_account_id, external_conversation_id),
            ).fetchone()
        return self._row_to_conversation(row) if row is not None else None

    def get_by_external_id(
        self, user_id: str, linked_account_id: str, external_conversation_id: str
    ) -> ConversationRecord | None:
        return self.get_conversation_by_external_id(
            user_id,
            linked_account_id,
            external_conversation_id,
        )

    def get_conversation(self, conversation_id: str) -> ConversationRecord | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, user_id, linked_account_id, provider, external_conversation_id,
                       title, preview, last_message_at, source_folder, status, metadata_json,
                       created_at, updated_at
                FROM conversations
                WHERE id = ?
                """,
                (conversation_id,),
            ).fetchone()
        return self._row_to_conversation(row) if row is not None else None

    def get_external_id(self, conversation_id: str) -> str | None:
        conversation = self.get_conversation(conversation_id)
        return conversation.external_conversation_id if conversation else None

    def get_insight(self, conversation_id: str) -> ConversationInsightRecord | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT conversation_id, summary, action_items_json, deadlines_json,
                       extracted_tasks_json, requested_items_json, recommended_next_action,
                       action_states_json, analyzed_at, created_at, updated_at
                FROM conversation_insights
                WHERE conversation_id = ?
                """,
                (conversation_id,),
            ).fetchone()
        return self._row_to_insight(row) if row is not None else None

    def get_insight_by_external_id(
        self, user_id: str, linked_account_id: str, external_conversation_id: str
    ) -> ConversationInsightRecord | None:
        conversation = self.get_by_external_id(
            user_id,
            linked_account_id,
            external_conversation_id,
        )
        if conversation is None:
            return None
        return self.get_insight(conversation.id)

    def list_thread_summaries_by_action_state(
        self,
        user_id: str,
        linked_account_id: str,
        action_state: str,
        *,
        limit: int,
        query: str | None = None,
    ) -> list[ThreadSummary]:
        filters = [
            "c.user_id = ?",
            "c.linked_account_id = ?",
            "i.action_states_json LIKE ?",
        ]
        params: list[object] = [user_id, linked_account_id, f'%"{action_state}"%']
        if query:
            filters.append("(LOWER(c.title) LIKE ? OR LOWER(c.preview) LIKE ?)")
            like_value = f"%{query.lower()}%"
            params.extend([like_value, like_value])
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT c.external_conversation_id, c.title, c.preview, c.last_message_at,
                       c.metadata_json, i.action_states_json
                FROM conversations c
                JOIN conversation_insights i ON i.conversation_id = c.id
                WHERE {" AND ".join(filters)}
                ORDER BY c.last_message_at DESC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
        return [self._row_to_thread_summary(row) for row in rows]

    def count_action_states(
        self, user_id: str, linked_account_id: str
    ) -> dict[str, int]:
        counts = {
            ActionState.TO_REPLY.value: 0,
            ActionState.TO_FOLLOW_UP.value: 0,
        }
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT i.action_states_json
                FROM conversations c
                JOIN conversation_insights i ON i.conversation_id = c.id
                WHERE c.user_id = ? AND c.linked_account_id = ?
                """,
                (user_id, linked_account_id),
            ).fetchall()
        for row in rows:
            for state in self._load_list(row["action_states_json"]):
                if state in counts:
                    counts[state] += 1
        return counts
        return counts

    def upsert_insight(self, insight: ConversationInsightRecord) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO conversation_insights (
                    conversation_id,
                    summary,
                    action_items_json,
                    deadlines_json,
                    extracted_tasks_json,
                    requested_items_json,
                    recommended_next_action,
                    action_states_json,
                    analyzed_at,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(conversation_id) DO UPDATE SET
                    summary = excluded.summary,
                    action_items_json = excluded.action_items_json,
                    deadlines_json = excluded.deadlines_json,
                    extracted_tasks_json = excluded.extracted_tasks_json,
                    requested_items_json = excluded.requested_items_json,
                    recommended_next_action = excluded.recommended_next_action,
                    action_states_json = excluded.action_states_json,
                    analyzed_at = excluded.analyzed_at,
                    updated_at = excluded.updated_at
                """,
                (
                    insight.conversation_id,
                    insight.summary,
                    self._dump_json(insight.action_items),
                    self._dump_json(insight.deadlines),
                    self._dump_json(insight.extracted_tasks),
                    self._dump_json(insight.requested_items),
                    insight.recommended_next_action,
                    self._dump_json(insight.action_states),
                    self._serialize_datetime(insight.analyzed_at),
                    insight.created_at.isoformat(),
                    insight.updated_at.isoformat(),
                ),
            )
            connection.commit()

    def _init_db(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    linked_account_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    external_conversation_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    preview TEXT NOT NULL,
                    last_message_at TEXT NOT NULL,
                    source_folder TEXT,
                    status TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(linked_account_id, external_conversation_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_insights (
                    conversation_id TEXT PRIMARY KEY,
                    summary TEXT,
                    action_items_json TEXT NOT NULL,
                    deadlines_json TEXT NOT NULL,
                    extracted_tasks_json TEXT NOT NULL DEFAULT '[]',
                    requested_items_json TEXT NOT NULL,
                    recommended_next_action TEXT,
                    action_states_json TEXT NOT NULL,
                    analyzed_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(conversation_insights)"
                ).fetchall()
            }
            if "extracted_tasks_json" not in columns:
                connection.execute(
                    """
                    ALTER TABLE conversation_insights
                    ADD COLUMN extracted_tasks_json TEXT NOT NULL DEFAULT '[]'
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

    def _row_to_conversation(self, row: sqlite3.Row) -> ConversationRecord:
        return ConversationRecord(
            id=row["id"],
            user_id=row["user_id"],
            linked_account_id=row["linked_account_id"],
            provider=row["provider"],
            external_conversation_id=row["external_conversation_id"],
            title=row["title"],
            preview=row["preview"],
            last_message_at=self._parse_datetime(row["last_message_at"]),
            source_folder=row["source_folder"],
            status=row["status"],
            metadata=self._load_dict(row["metadata_json"]),
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
        )

    def _row_to_insight(self, row: sqlite3.Row) -> ConversationInsightRecord:
        return ConversationInsightRecord(
            conversation_id=row["conversation_id"],
            summary=row["summary"],
            action_items=self._load_list(row["action_items_json"]),
            deadlines=self._load_deadlines(row["deadlines_json"]),
            extracted_tasks=self._load_extracted_tasks(row["extracted_tasks_json"]),
            requested_items=self._load_list(row["requested_items_json"]),
            recommended_next_action=row["recommended_next_action"],
            action_states=self._load_list(row["action_states_json"]),
            analyzed_at=self._parse_optional_datetime(row["analyzed_at"]),
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
        )

    def _row_to_thread_summary(self, row: sqlite3.Row) -> ThreadSummary:
        metadata = self._load_dict(row["metadata_json"])
        participants = metadata.get("participants")
        return ThreadSummary(
            id=row["external_conversation_id"],
            subject=row["title"],
            snippet=row["preview"],
            participants=participants if isinstance(participants, list) else [],
            last_message_at=self._parse_datetime(row["last_message_at"]),
            action_states=self._load_list(row["action_states_json"]),
        )


class PostgresConversationStore(_BaseConversationStore):
    def __init__(self, database_url: str) -> None:
        super().__init__()
        self.database_url = database_url
        self._init_db()

    def clear(self) -> None:
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM conversation_insights")
                cursor.execute("DELETE FROM conversations")
            connection.commit()

    def upsert_conversation(
        self, conversation: ConversationRecord
    ) -> ConversationRecord:
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO conversations (
                        id,
                        user_id,
                        linked_account_id,
                        provider,
                        external_conversation_id,
                        title,
                        preview,
                        last_message_at,
                        source_folder,
                        status,
                        metadata_json,
                        created_at,
                        updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (linked_account_id, external_conversation_id) DO UPDATE SET
                        title = excluded.title,
                        preview = excluded.preview,
                        last_message_at = excluded.last_message_at,
                        source_folder = excluded.source_folder,
                        status = excluded.status,
                        metadata_json = excluded.metadata_json,
                        updated_at = excluded.updated_at
                    RETURNING id, user_id, linked_account_id, provider, external_conversation_id,
                              title, preview, last_message_at, source_folder, status,
                              metadata_json, created_at, updated_at
                    """,
                    (
                        conversation.id,
                        conversation.user_id,
                        conversation.linked_account_id,
                        conversation.provider,
                        conversation.external_conversation_id,
                        conversation.title,
                        conversation.preview,
                        conversation.last_message_at,
                        conversation.source_folder,
                        conversation.status,
                        self._dump_json(conversation.metadata),
                        conversation.created_at,
                        conversation.updated_at,
                    ),
                )
                row = cursor.fetchone()
            connection.commit()
        if row is None:
            raise RuntimeError("Failed to persist conversation.")
        return self._pg_row_to_conversation(row)

    def get_conversation_by_external_id(
        self, user_id: str, linked_account_id: str, external_conversation_id: str
    ) -> ConversationRecord | None:
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, user_id, linked_account_id, provider, external_conversation_id,
                           title, preview, last_message_at, source_folder, status, metadata_json,
                           created_at, updated_at
                    FROM conversations
                    WHERE user_id = %s AND linked_account_id = %s AND external_conversation_id = %s
                    """,
                    (user_id, linked_account_id, external_conversation_id),
                )
                row = cursor.fetchone()
        return self._pg_row_to_conversation(row) if row is not None else None

    def get_by_external_id(
        self, user_id: str, linked_account_id: str, external_conversation_id: str
    ) -> ConversationRecord | None:
        return self.get_conversation_by_external_id(
            user_id,
            linked_account_id,
            external_conversation_id,
        )

    def get_conversation(self, conversation_id: str) -> ConversationRecord | None:
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, user_id, linked_account_id, provider, external_conversation_id,
                           title, preview, last_message_at, source_folder, status, metadata_json,
                           created_at, updated_at
                    FROM conversations
                    WHERE id = %s
                    """,
                    (conversation_id,),
                )
                row = cursor.fetchone()
        return self._pg_row_to_conversation(row) if row is not None else None

    def get_external_id(self, conversation_id: str) -> str | None:
        conversation = self.get_conversation(conversation_id)
        return conversation.external_conversation_id if conversation else None

    def get_insight(self, conversation_id: str) -> ConversationInsightRecord | None:
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT conversation_id, summary, action_items_json, deadlines_json,
                           extracted_tasks_json, requested_items_json,
                           recommended_next_action, action_states_json, analyzed_at,
                           created_at, updated_at
                    FROM conversation_insights
                    WHERE conversation_id = %s
                    """,
                    (conversation_id,),
                )
                row = cursor.fetchone()
        return self._pg_row_to_insight(row) if row is not None else None

    def get_insight_by_external_id(
        self, user_id: str, linked_account_id: str, external_conversation_id: str
    ) -> ConversationInsightRecord | None:
        conversation = self.get_by_external_id(
            user_id,
            linked_account_id,
            external_conversation_id,
        )
        if conversation is None:
            return None
        return self.get_insight(conversation.id)

    def list_thread_summaries_by_action_state(
        self,
        user_id: str,
        linked_account_id: str,
        action_state: str,
        *,
        limit: int,
        query: str | None = None,
    ) -> list[ThreadSummary]:
        filters = [
            "c.user_id = %s",
            "c.linked_account_id = %s",
            "i.action_states_json LIKE %s",
        ]
        params: list[object] = [user_id, linked_account_id, f'%"{action_state}"%']
        if query:
            filters.append("(LOWER(c.title) LIKE %s OR LOWER(c.preview) LIKE %s)")
            like_value = f"%{query.lower()}%"
            params.extend([like_value, like_value])
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT c.external_conversation_id, c.title, c.preview, c.last_message_at,
                           c.metadata_json, i.action_states_json
                    FROM conversations c
                    JOIN conversation_insights i ON i.conversation_id = c.id
                    WHERE {" AND ".join(filters)}
                    ORDER BY c.last_message_at DESC
                    LIMIT %s
                    """,
                    (*params, limit),
                )
                rows = cursor.fetchall()
        return [self._pg_row_to_thread_summary(row) for row in rows]

    def count_action_states(
        self, user_id: str, linked_account_id: str
    ) -> dict[str, int]:
        counts = {
            ActionState.TO_REPLY.value: 0,
            ActionState.TO_FOLLOW_UP.value: 0,
        }
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT i.action_states_json
                    FROM conversations c
                    JOIN conversation_insights i ON i.conversation_id = c.id
                    WHERE c.user_id = %s AND c.linked_account_id = %s
                    """,
                    (user_id, linked_account_id),
                )
                rows = cursor.fetchall()
        for row in rows:
            for state in self._load_list(row["action_states_json"]):
                if state in counts:
                    counts[state] += 1

    def upsert_insight(self, insight: ConversationInsightRecord) -> None:
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO conversation_insights (
                        conversation_id,
                        summary,
                        action_items_json,
                        deadlines_json,
                        extracted_tasks_json,
                        requested_items_json,
                        recommended_next_action,
                        action_states_json,
                        analyzed_at,
                        created_at,
                        updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (conversation_id) DO UPDATE SET
                        summary = excluded.summary,
                        action_items_json = excluded.action_items_json,
                        deadlines_json = excluded.deadlines_json,
                        extracted_tasks_json = excluded.extracted_tasks_json,
                        requested_items_json = excluded.requested_items_json,
                        recommended_next_action = excluded.recommended_next_action,
                        action_states_json = excluded.action_states_json,
                        analyzed_at = excluded.analyzed_at,
                        updated_at = excluded.updated_at
                    """,
                    (
                        insight.conversation_id,
                        insight.summary,
                        self._dump_json(insight.action_items),
                        self._dump_json(insight.deadlines),
                        self._dump_json(insight.extracted_tasks),
                        self._dump_json(insight.requested_items),
                        insight.recommended_next_action,
                        self._dump_json(insight.action_states),
                        insight.analyzed_at,
                        insight.created_at,
                        insight.updated_at,
                    ),
                )
            connection.commit()

    def _init_db(self) -> None:
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS conversations (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        linked_account_id TEXT NOT NULL,
                        provider TEXT NOT NULL,
                        external_conversation_id TEXT NOT NULL,
                        title TEXT NOT NULL,
                        preview TEXT NOT NULL,
                        last_message_at TIMESTAMPTZ NOT NULL,
                        source_folder TEXT NULL,
                        status TEXT NOT NULL,
                        metadata_json TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL,
                        UNIQUE(linked_account_id, external_conversation_id)
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS conversation_insights (
                        conversation_id TEXT PRIMARY KEY,
                        summary TEXT NULL,
                        action_items_json TEXT NOT NULL,
                        deadlines_json TEXT NOT NULL,
                        extracted_tasks_json TEXT NOT NULL DEFAULT '[]',
                        requested_items_json TEXT NOT NULL,
                        recommended_next_action TEXT NULL,
                        action_states_json TEXT NOT NULL,
                        analyzed_at TIMESTAMPTZ NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE conversation_insights
                    ADD COLUMN IF NOT EXISTS extracted_tasks_json TEXT NOT NULL DEFAULT '[]'
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

    def _pg_row_to_conversation(self, row: dict[str, Any]) -> ConversationRecord:
        return ConversationRecord(
            id=str(row["id"]),
            user_id=str(row["user_id"]),
            linked_account_id=str(row["linked_account_id"]),
            provider=str(row["provider"]),
            external_conversation_id=str(row["external_conversation_id"]),
            title=str(row["title"]),
            preview=str(row["preview"]),
            last_message_at=self._parse_datetime(row["last_message_at"]),
            source_folder=row["source_folder"],
            status=str(row["status"]),
            metadata=self._load_dict(row["metadata_json"]),
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
        )

    def _pg_row_to_insight(self, row: dict[str, Any]) -> ConversationInsightRecord:
        return ConversationInsightRecord(
            conversation_id=str(row["conversation_id"]),
            summary=row["summary"],
            action_items=self._load_list(row["action_items_json"]),
            deadlines=self._load_deadlines(row["deadlines_json"]),
            extracted_tasks=self._load_extracted_tasks(row["extracted_tasks_json"]),
            requested_items=self._load_list(row["requested_items_json"]),
            recommended_next_action=row["recommended_next_action"],
            action_states=self._load_list(row["action_states_json"]),
            analyzed_at=self._parse_optional_datetime(row["analyzed_at"]),
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
        )

    def _pg_row_to_thread_summary(self, row: dict[str, Any]) -> ThreadSummary:
        metadata = self._load_dict(row["metadata_json"])
        participants = metadata.get("participants")
        return ThreadSummary(
            id=str(row["external_conversation_id"]),
            subject=str(row["title"]),
            snippet=str(row["preview"]),
            participants=participants if isinstance(participants, list) else [],
            last_message_at=self._parse_datetime(row["last_message_at"]),
            action_states=self._load_list(row["action_states_json"]),
        )


def build_conversation_store(database_url: str) -> ConversationStore:
    if database_url.startswith("sqlite:///"):
        return SQLiteConversationStore(database_url)
    return PostgresConversationStore(database_url)


def new_conversation_record(
    user_id: str,
    linked_account_id: str,
    provider: str,
    external_conversation_id: str,
    *,
    title: str,
    preview: str,
    last_message_at: datetime,
    source_folder: str | None,
    status: str = "open",
) -> ConversationRecord:
    now = datetime.now(UTC)
    return ConversationRecord(
        id=new_id("conv"),
        user_id=user_id,
        linked_account_id=linked_account_id,
        provider=provider,
        external_conversation_id=external_conversation_id,
        title=title,
        preview=preview,
        last_message_at=last_message_at,
        source_folder=source_folder,
        status=status,
        metadata={},
        created_at=now,
        updated_at=now,
    )


def build_placeholder_conversation(
    user_id: str,
    linked_account_id: str,
    provider: str,
    external_conversation_id: str,
    *,
    title: str,
    preview: str,
    last_message_at: datetime,
    source_folder: str | None,
    status: str = "open",
) -> ConversationRecord:
    return new_conversation_record(
        user_id=user_id,
        linked_account_id=linked_account_id,
        provider=provider,
        external_conversation_id=external_conversation_id,
        title=title,
        preview=preview,
        last_message_at=last_message_at,
        source_folder=source_folder,
        status=status,
    )


def build_insight_record(
    *,
    conversation_id: str,
    thread: ThreadSummary | ThreadDetail,
) -> ConversationInsightRecord:
    analysis: ThreadAnalysis | None = getattr(thread, "analysis", None)
    now = datetime.now(UTC)
    return ConversationInsightRecord(
        conversation_id=conversation_id,
        summary=analysis.summary if analysis else None,
        action_items=list(analysis.action_items) if analysis else [],
        deadlines=list(analysis.deadlines) if analysis else [],
        extracted_tasks=list(analysis.extracted_tasks) if analysis else [],
        requested_items=list(analysis.requested_items) if analysis else [],
        recommended_next_action=analysis.recommended_next_action if analysis else None,
        action_states=[
            state.value if hasattr(state, "value") else str(state)
            for state in thread.action_states
        ],
        analyzed_at=analysis.analyzed_at if analysis else None,
        created_at=now,
        updated_at=now,
    )
