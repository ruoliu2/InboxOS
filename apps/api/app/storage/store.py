from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock

from app.schemas.common import SyncStatus
from app.schemas.task import TaskItem
from app.schemas.thread import ThreadDetail


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
    created_at: datetime
    updated_at: datetime


class InMemoryStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self.threads: dict[str, ThreadDetail] = {}
        self.tasks: dict[str, TaskItem] = {}
        self.oauth_states: dict[str, OAuthStateRecord] = {}
        self.sessions: dict[str, AuthSessionRecord] = {}
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

    def save_oauth_state(self, state: OAuthStateRecord) -> None:
        with self._lock:
            self.oauth_states[state.state] = state

    def pop_oauth_state(self, state: str) -> OAuthStateRecord | None:
        with self._lock:
            return self.oauth_states.pop(state, None)

    def upsert_session(self, session: AuthSessionRecord) -> None:
        with self._lock:
            self.sessions[session.session_id] = session

    def get_session(self, session_id: str) -> AuthSessionRecord | None:
        with self._lock:
            return self.sessions.get(session_id)

    def delete_session(self, session_id: str) -> None:
        with self._lock:
            self.sessions.pop(session_id, None)


_store = InMemoryStore()


def get_store() -> InMemoryStore:
    return _store
