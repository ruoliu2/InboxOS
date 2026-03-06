from datetime import datetime

from pydantic import BaseModel

from app.schemas.common import TaskStatus


class CreateTaskRequest(BaseModel):
    title: str
    due_at: datetime | None = None
    thread_id: str | None = None
    category: str | None = None


class TaskItem(BaseModel):
    id: str
    title: str
    status: TaskStatus
    due_at: datetime | None = None
    thread_id: str | None = None
    category: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


class CompleteTaskResponse(BaseModel):
    task_id: str
    status: TaskStatus
    completed_at: datetime
