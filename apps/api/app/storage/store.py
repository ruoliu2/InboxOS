from __future__ import annotations

from threading import Lock

from app.schemas.task import TaskItem


class InMemoryStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self.tasks: dict[str, TaskItem] = {}

    def upsert_task(self, task: TaskItem) -> None:
        with self._lock:
            self.tasks[task.id] = task


_store = InMemoryStore()


def get_store() -> InMemoryStore:
    return _store
