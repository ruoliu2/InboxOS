from datetime import UTC, datetime

from app.schemas.common import TaskStatus
from app.schemas.task import TaskItem
from app.storage.task_store import SQLiteTaskStore


def test_sqlite_task_store_lists_tasks_without_conversation_store(tmp_path):
    store = SQLiteTaskStore(f"sqlite:///{tmp_path / 'tasks.sqlite3'}")
    task = TaskItem(
        id="task-1",
        title="Follow up",
        status=TaskStatus.OPEN,
        linked_account_id="acct-1",
        conversation_id="conv-1",
        thread_id="thread-123",
        category="email",
        created_at=datetime.now(UTC),
    )

    store.upsert_task("usr-1", task)

    tasks = store.list_tasks("usr-1")

    assert len(tasks) == 1
    assert tasks[0].thread_id == "thread-123"
