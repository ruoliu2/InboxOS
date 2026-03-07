from fastapi import APIRouter, Depends, HTTPException

from app.schemas.task import CompleteTaskResponse, CreateTaskRequest, TaskItem
from app.services.dependencies import get_current_auth_session, get_task_service
from app.services.task_service import TaskService
from app.storage.auth_store import AuthSessionRecord

router = APIRouter()


@router.get("", response_model=list[TaskItem])
def list_tasks(
    session: AuthSessionRecord = Depends(get_current_auth_session),
    service: TaskService = Depends(get_task_service),
) -> list[TaskItem]:
    return service.list_tasks(session.user_id)


@router.post("/create", response_model=TaskItem)
def create_task(
    payload: CreateTaskRequest,
    session: AuthSessionRecord = Depends(get_current_auth_session),
    service: TaskService = Depends(get_task_service),
) -> TaskItem:
    return service.create_task(
        session.user_id,
        session.active_linked_account_id,
        session.provider,
        payload,
    )


@router.post("/{task_id}/complete", response_model=CompleteTaskResponse)
def complete_task(
    task_id: str,
    session: AuthSessionRecord = Depends(get_current_auth_session),
    service: TaskService = Depends(get_task_service),
) -> CompleteTaskResponse:
    try:
        task = service.complete_task(session.user_id, task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return CompleteTaskResponse(
        task_id=task.id,
        status=task.status,
        completed_at=task.completed_at,
    )
