from __future__ import annotations

from datetime import UTC, datetime

from app.schemas.common import TaskOrigin, TaskStatus
from app.schemas.task import CreateTaskRequest, TaskItem
from app.services.id_factory import new_id
from app.storage.conversation_store import (
    ConversationStore,
    new_conversation_record,
)
from app.storage.task_store import TaskStore


class TaskService:
    def __init__(self, store: TaskStore, conversation_store: ConversationStore) -> None:
        self.store = store
        self.conversation_store = conversation_store

    def list_tasks(self, user_id: str) -> list[TaskItem]:
        tasks = self.store.list_tasks(user_id)
        tasks.sort(key=lambda task: task.created_at, reverse=True)
        return tasks

    def create_task(
        self,
        user_id: str,
        active_linked_account_id: str | None,
        active_provider: str | None,
        payload: CreateTaskRequest,
    ) -> TaskItem:
        linked_account_id = payload.linked_account_id or active_linked_account_id
        conversation_id = payload.conversation_id
        thread_id = payload.thread_id
        if (
            conversation_id is None
            and thread_id
            and linked_account_id
            and active_provider
        ):
            existing = self.conversation_store.get_by_external_id(
                user_id,
                linked_account_id,
                thread_id,
            )
            if existing is not None:
                conversation_id = existing.id
            else:
                placeholder = new_conversation_record(
                    user_id=user_id,
                    linked_account_id=linked_account_id,
                    provider=active_provider,
                    external_conversation_id=thread_id,
                    title=payload.title,
                    preview=payload.title,
                    last_message_at=datetime.now(UTC),
                    source_folder=None,
                )
                conversation_id = self.conversation_store.upsert_conversation(
                    placeholder
                ).id
        task = TaskItem(
            id=new_id("task"),
            title=payload.title,
            status=TaskStatus.OPEN,
            due_at=payload.due_at,
            linked_account_id=linked_account_id,
            conversation_id=conversation_id,
            thread_id=payload.thread_id,
            category=payload.category,
            origin=payload.origin or TaskOrigin.MANUAL,
            origin_key=payload.origin_key,
            deadline_source=payload.deadline_source,
            created_at=datetime.now(UTC),
        )
        self.store.upsert_task(user_id, task)
        return task

    def complete_task(self, user_id: str, task_id: str) -> TaskItem:
        task = self.store.get_task(user_id, task_id)
        if task is None:
            raise KeyError(f"task {task_id} not found")

        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.now(UTC)
        self.store.upsert_task(user_id, task)
        return task
