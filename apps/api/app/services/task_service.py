from __future__ import annotations

from datetime import UTC, datetime

from app.schemas.common import TaskStatus
from app.schemas.task import CreateTaskRequest, TaskItem
from app.schemas.thread import ThreadDetail
from app.services.id_factory import new_id
from app.storage.task_store import TaskStore


class TaskService:
    def __init__(self, store: TaskStore) -> None:
        self.store = store

    def list_tasks(self, account_email: str) -> list[TaskItem]:
        tasks = self.store.list_tasks(account_email)
        tasks.sort(key=lambda task: task.created_at, reverse=True)
        return tasks

    def create_task(self, account_email: str, payload: CreateTaskRequest) -> TaskItem:
        task = TaskItem(
            id=new_id("task"),
            title=payload.title,
            status=TaskStatus.OPEN,
            due_at=payload.due_at,
            thread_id=payload.thread_id,
            category=payload.category,
            created_at=datetime.now(UTC),
        )
        self.store.upsert_task(account_email, task)
        return task

    def complete_task(self, account_email: str, task_id: str) -> TaskItem:
        task = self.store.get_task(account_email, task_id)
        if task is None:
            raise KeyError(f"task {task_id} not found")

        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.now(UTC)
        self.store.upsert_task(account_email, task)
        return task

    def create_tasks_for_thread(
        self, account_email: str, thread: ThreadDetail
    ) -> list[TaskItem]:
        if thread.analysis is None:
            return []

        created: list[TaskItem] = []
        existing_titles = self.store.list_open_titles_for_thread(
            account_email,
            thread.id,
        )

        for deadline in thread.analysis.deadlines:
            title = f"{thread.subject} (deadline {deadline})"
            if title in existing_titles:
                continue
            task = self.create_task(
                account_email,
                CreateTaskRequest(
                    title=title,
                    thread_id=thread.id,
                    category="deadline",
                ),
            )
            created.append(task)
            existing_titles.add(title)

        return created
