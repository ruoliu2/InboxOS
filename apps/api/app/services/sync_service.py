from datetime import UTC, datetime

from app.integrations.mail.base import MailSyncAdapter
from app.schemas.common import SyncStatus
from app.schemas.sync import SyncStartRequest
from app.services.task_service import TaskService
from app.services.thread_service import ThreadService
from app.storage.store import InMemoryStore


class SyncService:
    def __init__(
        self,
        store: InMemoryStore,
        mail_adapter: MailSyncAdapter,
        thread_service: ThreadService,
        task_service: TaskService,
    ) -> None:
        self.store = store
        self.mail_adapter = mail_adapter
        self.thread_service = thread_service
        self.task_service = task_service

    def start_sync(
        self, payload: SyncStartRequest, *, account_email: str
    ) -> dict[str, object]:
        sync_id = f"sync_{int(datetime.now(UTC).timestamp())}"
        self.store.sync_status = {
            "sync_id": sync_id,
            "status": SyncStatus.RUNNING,
            "imported_threads": 0,
            "updated_at": datetime.now(UTC),
            "last_error": None,
        }

        try:
            effective_account = payload.account_email or account_email
            threads = self.mail_adapter.sync_threads(effective_account)
            self.store.set_threads(threads)

            for thread in threads:
                analyzed_thread, _ = self.thread_service.analyze_thread(thread.id)
                self.task_service.create_tasks_for_thread(
                    account_email, analyzed_thread
                )

            self.store.sync_status = {
                "sync_id": sync_id,
                "status": SyncStatus.COMPLETED,
                "imported_threads": len(threads),
                "updated_at": datetime.now(UTC),
                "last_error": None,
            }
        except Exception as exc:  # pragma: no cover - defensive fallback
            self.store.sync_status = {
                "sync_id": sync_id,
                "status": SyncStatus.FAILED,
                "imported_threads": 0,
                "updated_at": datetime.now(UTC),
                "last_error": str(exc),
            }

        return self.store.sync_status

    def get_status(self) -> dict[str, object]:
        return self.store.sync_status
