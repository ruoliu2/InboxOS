from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Protocol
from urllib.parse import unquote, urlparse

import psycopg
from psycopg.rows import dict_row

from app.schemas.task import TaskItem


class TaskStore(Protocol):
    def list_tasks(self, user_id: str) -> list[TaskItem]: ...

    def get_task(self, user_id: str, task_id: str) -> TaskItem | None: ...

    def get_task_by_origin_key(
        self, user_id: str, origin_key: str
    ) -> TaskItem | None: ...

    def upsert_task(self, user_id: str, task: TaskItem) -> None: ...

    def clear(self) -> None: ...


class SQLiteTaskStore:
    def __init__(self, database_url: str) -> None:
        parsed = urlparse(database_url)
        if parsed.scheme != "sqlite":
            raise ValueError(f"Unsupported SQLite task database URL: {database_url}")

        raw_path = unquote(parsed.path)
        self.db_path = Path(raw_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._init_db()

    def list_tasks(self, user_id: str) -> list[TaskItem]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, title, status, due_at, linked_account_id, conversation_id,
                       thread_id, category, origin, origin_key, deadline_source,
                       created_at, completed_at
                FROM tasks
                WHERE user_id = ?
                ORDER BY created_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [self._row_to_task(row) for row in rows]

    def get_task(self, user_id: str, task_id: str) -> TaskItem | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, title, status, due_at, linked_account_id, conversation_id,
                       thread_id, category, origin, origin_key, deadline_source,
                       created_at, completed_at
                FROM tasks
                WHERE user_id = ? AND id = ?
                """,
                (user_id, task_id),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_task(row)

    def get_task_by_origin_key(self, user_id: str, origin_key: str) -> TaskItem | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, title, status, due_at, linked_account_id, conversation_id,
                       thread_id, category, origin, origin_key, deadline_source,
                       created_at, completed_at
                FROM tasks
                WHERE user_id = ? AND origin_key = ?
                """,
                (user_id, origin_key),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_task(row)

    def upsert_task(self, user_id: str, task: TaskItem) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO tasks (
                    id,
                    user_id,
                    title,
                    status,
                    due_at,
                    linked_account_id,
                    conversation_id,
                    thread_id,
                    category,
                    origin,
                    origin_key,
                    deadline_source,
                    created_at,
                    completed_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    user_id = excluded.user_id,
                    title = excluded.title,
                    status = excluded.status,
                    due_at = excluded.due_at,
                    linked_account_id = excluded.linked_account_id,
                    conversation_id = excluded.conversation_id,
                    thread_id = excluded.thread_id,
                    category = excluded.category,
                    origin = excluded.origin,
                    origin_key = excluded.origin_key,
                    deadline_source = excluded.deadline_source,
                    created_at = excluded.created_at,
                    completed_at = excluded.completed_at,
                    updated_at = excluded.updated_at
                """,
                (
                    task.id,
                    user_id,
                    task.title,
                    task.status,
                    self._serialize_datetime(task.due_at),
                    task.linked_account_id,
                    task.conversation_id,
                    task.thread_id,
                    task.category,
                    task.origin,
                    task.origin_key,
                    task.deadline_source,
                    task.created_at.isoformat(),
                    self._serialize_datetime(task.completed_at),
                    datetime.now().astimezone().isoformat(),
                ),
            )
            connection.commit()

    def clear(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM tasks")
            connection.commit()

    def _init_db(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    due_at TEXT,
                    linked_account_id TEXT,
                    conversation_id TEXT,
                    thread_id TEXT,
                    category TEXT,
                    origin TEXT NOT NULL DEFAULT 'manual',
                    origin_key TEXT,
                    deadline_source TEXT,
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_tasks_user_created
                ON tasks (user_id, created_at DESC)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_tasks_user_conversation_status
                ON tasks (user_id, conversation_id, status)
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(tasks)").fetchall()
            }
            if "thread_id" not in columns:
                connection.execute("ALTER TABLE tasks ADD COLUMN thread_id TEXT")
            if "origin" not in columns:
                connection.execute(
                    "ALTER TABLE tasks ADD COLUMN origin TEXT NOT NULL DEFAULT 'manual'"
                )
            if "origin_key" not in columns:
                connection.execute("ALTER TABLE tasks ADD COLUMN origin_key TEXT")
            if "deadline_source" not in columns:
                connection.execute("ALTER TABLE tasks ADD COLUMN deadline_source TEXT")
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_user_origin_key
                ON tasks (user_id, origin_key)
                WHERE origin = 'agent' AND origin_key IS NOT NULL
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

    def _row_to_task(self, row: sqlite3.Row) -> TaskItem:
        return TaskItem(
            id=row["id"],
            title=row["title"],
            status=row["status"],
            due_at=self._parse_optional_datetime(row["due_at"]),
            linked_account_id=row["linked_account_id"],
            conversation_id=row["conversation_id"],
            thread_id=row["thread_id"],
            category=row["category"],
            origin=row["origin"] or "manual",
            origin_key=row["origin_key"],
            deadline_source=row["deadline_source"],
            created_at=self._parse_datetime(row["created_at"]),
            completed_at=self._parse_optional_datetime(row["completed_at"]),
        )

    def _serialize_datetime(self, value: datetime | None) -> str | None:
        return value.isoformat() if value is not None else None

    def _parse_optional_datetime(self, value: str | None) -> datetime | None:
        return self._parse_datetime(value) if value else None

    def _parse_datetime(self, value: str) -> datetime:
        return datetime.fromisoformat(value)


class PostgresTaskStore:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._lock = Lock()
        self._init_db()

    def list_tasks(self, user_id: str) -> list[TaskItem]:
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, title, status, due_at, linked_account_id,
                           conversation_id, thread_id, category, origin,
                           origin_key, deadline_source, created_at, completed_at
                    FROM tasks
                    WHERE user_id = %s
                    ORDER BY created_at DESC
                    """,
                    (user_id,),
                )
                rows = cursor.fetchall()
        return [self._row_to_task(row) for row in rows]

    def get_task(self, user_id: str, task_id: str) -> TaskItem | None:
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, title, status, due_at, linked_account_id,
                           conversation_id, thread_id, category, origin,
                           origin_key, deadline_source, created_at, completed_at
                    FROM tasks
                    WHERE user_id = %s AND id = %s
                    """,
                    (user_id, task_id),
                )
                row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_task(row)

    def get_task_by_origin_key(self, user_id: str, origin_key: str) -> TaskItem | None:
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, title, status, due_at, linked_account_id,
                           conversation_id, thread_id, category, origin,
                           origin_key, deadline_source, created_at, completed_at
                    FROM tasks
                    WHERE user_id = %s AND origin_key = %s
                    """,
                    (user_id, origin_key),
                )
                row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_task(row)

    def upsert_task(self, user_id: str, task: TaskItem) -> None:
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO tasks (
                        id,
                        user_id,
                        title,
                        status,
                        due_at,
                        linked_account_id,
                        conversation_id,
                        thread_id,
                        category,
                        origin,
                        origin_key,
                        deadline_source,
                        created_at,
                        completed_at,
                        updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        user_id = excluded.user_id,
                        title = excluded.title,
                        status = excluded.status,
                        due_at = excluded.due_at,
                        linked_account_id = excluded.linked_account_id,
                        conversation_id = excluded.conversation_id,
                        thread_id = excluded.thread_id,
                        category = excluded.category,
                        origin = excluded.origin,
                        origin_key = excluded.origin_key,
                        deadline_source = excluded.deadline_source,
                        created_at = excluded.created_at,
                        completed_at = excluded.completed_at,
                        updated_at = excluded.updated_at
                    """,
                    (
                        task.id,
                        user_id,
                        task.title,
                        task.status,
                        task.due_at,
                        task.linked_account_id,
                        task.conversation_id,
                        task.thread_id,
                        task.category,
                        task.origin,
                        task.origin_key,
                        task.deadline_source,
                        task.created_at,
                        task.completed_at,
                        datetime.now().astimezone(),
                    ),
                )
            connection.commit()

    def clear(self) -> None:
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM tasks")
            connection.commit()

    def _init_db(self) -> None:
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS tasks (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        title TEXT NOT NULL,
                        status TEXT NOT NULL,
                        due_at TIMESTAMPTZ NULL,
                        linked_account_id TEXT NULL,
                        conversation_id TEXT NULL,
                        thread_id TEXT NULL,
                        category TEXT NULL,
                        origin TEXT NOT NULL DEFAULT 'manual',
                        origin_key TEXT NULL,
                        deadline_source TEXT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        completed_at TIMESTAMPTZ NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                """
                )
                cursor.execute(
                    """
                    ALTER TABLE tasks
                    ADD COLUMN IF NOT EXISTS thread_id TEXT NULL
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE tasks
                    ADD COLUMN IF NOT EXISTS origin TEXT NOT NULL DEFAULT 'manual'
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE tasks
                    ADD COLUMN IF NOT EXISTS origin_key TEXT NULL
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE tasks
                    ADD COLUMN IF NOT EXISTS deadline_source TEXT NULL
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_tasks_user_created
                    ON tasks (user_id, created_at DESC)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_tasks_user_conversation_status
                    ON tasks (user_id, conversation_id, status)
                    """
                )
                cursor.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_user_origin_key
                    ON tasks (user_id, origin_key)
                    WHERE origin = 'agent' AND origin_key IS NOT NULL
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

    def _row_to_task(self, row: dict[str, object]) -> TaskItem:
        return TaskItem(
            id=str(row["id"]),
            title=str(row["title"]),
            status=str(row["status"]),
            due_at=row["due_at"],
            linked_account_id=row["linked_account_id"],
            conversation_id=row["conversation_id"],
            thread_id=row["thread_id"],
            category=row["category"],
            origin=str(row["origin"] or "manual"),
            origin_key=row["origin_key"],
            deadline_source=row["deadline_source"],
            created_at=row["created_at"],
            completed_at=row["completed_at"],
        )


def build_task_store(database_url: str) -> TaskStore:
    if database_url.startswith("sqlite:///"):
        return SQLiteTaskStore(database_url)
    return PostgresTaskStore(database_url)
