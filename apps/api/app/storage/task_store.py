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
    def list_tasks(self, account_email: str) -> list[TaskItem]: ...

    def get_task(self, account_email: str, task_id: str) -> TaskItem | None: ...

    def upsert_task(self, account_email: str, task: TaskItem) -> None: ...

    def list_open_titles_for_thread(
        self, account_email: str, thread_id: str
    ) -> set[str]: ...

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

    def list_tasks(self, account_email: str) -> list[TaskItem]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, title, status, due_at, thread_id, category, created_at,
                       completed_at
                FROM tasks
                WHERE account_email = ?
                ORDER BY created_at DESC
                """,
                (account_email,),
            ).fetchall()
        return [self._row_to_task(row) for row in rows]

    def get_task(self, account_email: str, task_id: str) -> TaskItem | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, title, status, due_at, thread_id, category, created_at,
                       completed_at
                FROM tasks
                WHERE account_email = ? AND id = ?
                """,
                (account_email, task_id),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_task(row)

    def upsert_task(self, account_email: str, task: TaskItem) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO tasks (
                    id,
                    account_email,
                    title,
                    status,
                    due_at,
                    thread_id,
                    category,
                    created_at,
                    completed_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    account_email = excluded.account_email,
                    title = excluded.title,
                    status = excluded.status,
                    due_at = excluded.due_at,
                    thread_id = excluded.thread_id,
                    category = excluded.category,
                    created_at = excluded.created_at,
                    completed_at = excluded.completed_at,
                    updated_at = excluded.updated_at
                """,
                (
                    task.id,
                    account_email,
                    task.title,
                    task.status,
                    self._serialize_datetime(task.due_at),
                    task.thread_id,
                    task.category,
                    task.created_at.isoformat(),
                    self._serialize_datetime(task.completed_at),
                    datetime.now().astimezone().isoformat(),
                ),
            )
            connection.commit()

    def list_open_titles_for_thread(
        self, account_email: str, thread_id: str
    ) -> set[str]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT title
                FROM tasks
                WHERE account_email = ? AND thread_id = ? AND status = 'open'
                """,
                (account_email, thread_id),
            ).fetchall()
        return {str(row["title"]) for row in rows}

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
                    account_email TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    due_at TEXT,
                    thread_id TEXT,
                    category TEXT,
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_tasks_account_created
                ON tasks (account_email, created_at DESC)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_tasks_account_thread_status
                ON tasks (account_email, thread_id, status)
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
            thread_id=row["thread_id"],
            category=row["category"],
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

    def list_tasks(self, account_email: str) -> list[TaskItem]:
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, title, status, due_at, thread_id, category,
                           created_at, completed_at
                    FROM tasks
                    WHERE account_email = %s
                    ORDER BY created_at DESC
                    """,
                    (account_email,),
                )
                rows = cursor.fetchall()
        return [self._row_to_task(row) for row in rows]

    def get_task(self, account_email: str, task_id: str) -> TaskItem | None:
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, title, status, due_at, thread_id, category,
                           created_at, completed_at
                    FROM tasks
                    WHERE account_email = %s AND id = %s
                    """,
                    (account_email, task_id),
                )
                row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_task(row)

    def upsert_task(self, account_email: str, task: TaskItem) -> None:
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO tasks (
                        id,
                        account_email,
                        title,
                        status,
                        due_at,
                        thread_id,
                        category,
                        created_at,
                        completed_at,
                        updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        account_email = excluded.account_email,
                        title = excluded.title,
                        status = excluded.status,
                        due_at = excluded.due_at,
                        thread_id = excluded.thread_id,
                        category = excluded.category,
                        created_at = excluded.created_at,
                        completed_at = excluded.completed_at,
                        updated_at = excluded.updated_at
                    """,
                    (
                        task.id,
                        account_email,
                        task.title,
                        task.status,
                        task.due_at,
                        task.thread_id,
                        task.category,
                        task.created_at,
                        task.completed_at,
                        datetime.now().astimezone(),
                    ),
                )
            connection.commit()

    def list_open_titles_for_thread(
        self, account_email: str, thread_id: str
    ) -> set[str]:
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT title
                    FROM tasks
                    WHERE account_email = %s AND thread_id = %s AND status = 'open'
                    """,
                    (account_email, thread_id),
                )
                rows = cursor.fetchall()
        return {str(row["title"]) for row in rows}

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
                        account_email TEXT NOT NULL,
                        title TEXT NOT NULL,
                        status TEXT NOT NULL,
                        due_at TIMESTAMPTZ NULL,
                        thread_id TEXT NULL,
                        category TEXT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        completed_at TIMESTAMPTZ NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_tasks_account_created
                    ON tasks (account_email, created_at DESC)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_tasks_account_thread_status
                    ON tasks (account_email, thread_id, status)
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
            thread_id=row["thread_id"],
            category=row["category"],
            created_at=row["created_at"],
            completed_at=row["completed_at"],
        )


def build_task_store(database_url: str) -> TaskStore:
    if database_url.startswith("sqlite:///"):
        return SQLiteTaskStore(database_url)
    return PostgresTaskStore(database_url)
