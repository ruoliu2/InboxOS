from __future__ import annotations

from datetime import UTC, datetime

from app.schemas.common import TaskStatus
from app.schemas.task import CreateTaskRequest, TaskItem
from app.schemas.thread import ThreadDetail
from app.services.id_factory import new_id
from app.storage.store import InMemoryStore


class TaskService:
    def __init__(self, store: InMemoryStore) -> None:
        self.store = store

    def list_tasks(self) -> list[TaskItem]:
        tasks = list(self.store.tasks.values())
        tasks.sort(key=lambda task: task.created_at, reverse=True)
        return tasks

    def create_task(self, payload: CreateTaskRequest) -> TaskItem:
        task = TaskItem(
            id=new_id("task"),
            title=payload.title,
            status=TaskStatus.OPEN,
            due_at=payload.due_at,
            thread_id=payload.thread_id,
            category=payload.category,
            created_at=datetime.now(UTC),
        )
        self.store.upsert_task(task)
        return task

    def complete_task(self, task_id: str) -> TaskItem:
        task = self.store.tasks.get(task_id)
        if task is None:
            raise KeyError(f"task {task_id} not found")

        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.now(UTC)
        self.store.upsert_task(task)
        return task

    def create_tasks_for_thread(self, thread: ThreadDetail) -> list[TaskItem]:
        if thread.analysis is None:
            return []

        created: list[TaskItem] = []
        existing_titles = {
            task.title
            for task in self.store.tasks.values()
            if task.thread_id == thread.id and task.status == TaskStatus.OPEN
        }

        for deadline in thread.analysis.deadlines:
            title = f"{thread.subject} (deadline {deadline})"
            if title in existing_titles:
                continue
            task = self.create_task(
                CreateTaskRequest(
                    title=title,
                    thread_id=thread.id,
                    category="deadline",
                )
            )
            created.append(task)
            existing_titles.add(title)

        return created
