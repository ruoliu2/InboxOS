from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from threading import Lock

from app.schemas.common import SyncStatus
from app.schemas.task import TaskItem
from app.schemas.thread import ThreadDetail


class InMemoryStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self.threads: dict[str, ThreadDetail] = {}
        self.tasks: dict[str, TaskItem] = {}
        self.sync_status: dict[str, object] = {
            "sync_id": None,
            "status": SyncStatus.IDLE,
            "imported_threads": 0,
            "updated_at": datetime.now(UTC),
            "last_error": None,
        }

    def set_threads(self, threads: Iterable[ThreadDetail]) -> None:
        with self._lock:
            self.threads = {thread.id: thread for thread in threads}

    def upsert_thread(self, thread: ThreadDetail) -> None:
        with self._lock:
            self.threads[thread.id] = thread

    def upsert_task(self, task: TaskItem) -> None:
        with self._lock:
            self.tasks[task.id] = task


_store = InMemoryStore()


def get_store() -> InMemoryStore:
    return _store
