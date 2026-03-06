from fastapi import APIRouter, Depends, HTTPException

from app.schemas.task import CompleteTaskResponse, CreateTaskRequest, TaskItem
from app.services.dependencies import get_task_service
from app.services.task_service import TaskService

router = APIRouter()


@router.get("", response_model=list[TaskItem])
def list_tasks(service: TaskService = Depends(get_task_service)) -> list[TaskItem]:
    return service.list_tasks()


@router.post("/create", response_model=TaskItem)
def create_task(
    payload: CreateTaskRequest,
    service: TaskService = Depends(get_task_service),
) -> TaskItem:
    return service.create_task(payload)


@router.post("/{task_id}/complete", response_model=CompleteTaskResponse)
def complete_task(
    task_id: str,
    service: TaskService = Depends(get_task_service),
) -> CompleteTaskResponse:
    try:
        task = service.complete_task(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return CompleteTaskResponse(
        task_id=task.id,
        status=task.status,
        completed_at=task.completed_at,
    )
