from fastapi import APIRouter, Depends, HTTPException

from app.schemas.task import CompleteTaskResponse, CreateTaskRequest, TaskItem
from app.services.auth_service import AuthService
from app.services.dependencies import (
    get_auth_service,
    get_current_auth_session,
    get_task_service,
)
from app.services.task_service import TaskService
from app.storage.auth_store import AuthSessionRecord

router = APIRouter()


def with_account_metadata(
    task: TaskItem,
    accounts_by_id: dict[str, object],
) -> TaskItem:
    if not task.linked_account_id:
        return task
    account = accounts_by_id.get(task.linked_account_id)
    if account is None:
        return task
    payload = task.model_dump()
    payload["account_email"] = getattr(account, "provider_account_ref", None)
    payload["account_name"] = getattr(account, "display_name", None)
    return TaskItem(**payload)


@router.get("", response_model=list[TaskItem])
def list_tasks(
    session: AuthSessionRecord = Depends(get_current_auth_session),
    service: TaskService = Depends(get_task_service),
    auth_service: AuthService = Depends(get_auth_service),
) -> list[TaskItem]:
    accounts_by_id = {
        account.id: account
        for account in auth_service.list_linked_accounts(session.user_id)
    }
    return [
        with_account_metadata(task, accounts_by_id)
        for task in service.list_tasks(session.user_id)
    ]


@router.post("/create", response_model=TaskItem)
def create_task(
    payload: CreateTaskRequest,
    session: AuthSessionRecord = Depends(get_current_auth_session),
    service: TaskService = Depends(get_task_service),
    auth_service: AuthService = Depends(get_auth_service),
) -> TaskItem:
    task = service.create_task(
        session.user_id,
        session.active_linked_account_id,
        session.provider,
        payload,
    )
    accounts_by_id = {
        account.id: account
        for account in auth_service.list_linked_accounts(session.user_id)
    }
    return with_account_metadata(task, accounts_by_id)


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
