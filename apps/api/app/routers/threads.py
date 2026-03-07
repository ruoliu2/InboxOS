from fastapi import APIRouter, Depends, HTTPException, Query

from app.schemas.common import ActionState
from app.schemas.thread import (
    AnalyzeThreadResponse,
    ReplyToThreadRequest,
    ReplyToThreadResponse,
    ThreadDetail,
    ThreadSummary,
)
from app.services.dependencies import (
    get_current_auth_session,
    get_task_service,
    get_thread_service,
)
from app.services.task_service import TaskService
from app.services.thread_service import ThreadService
from app.storage.auth_store import AuthSessionRecord

router = APIRouter()


@router.get("", response_model=list[ThreadSummary])
def list_threads(
    action_state: ActionState | None = Query(default=None),
    service: ThreadService = Depends(get_thread_service),
) -> list[ThreadSummary]:
    return service.list_threads(action_state=action_state)


@router.get("/{thread_id}", response_model=ThreadDetail)
def get_thread(
    thread_id: str,
    service: ThreadService = Depends(get_thread_service),
) -> ThreadDetail:
    try:
        return service.get_thread(thread_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{thread_id}/analyze", response_model=AnalyzeThreadResponse)
def analyze_thread(
    thread_id: str,
    session: AuthSessionRecord = Depends(get_current_auth_session),
    thread_service: ThreadService = Depends(get_thread_service),
    task_service: TaskService = Depends(get_task_service),
) -> AnalyzeThreadResponse:
    try:
        thread, analysis = thread_service.analyze_thread(thread_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    task_service.create_tasks_for_thread(session.account_email, thread)
    return AnalyzeThreadResponse(thread_id=thread_id, analysis=analysis)


@router.post("/{thread_id}/reply", response_model=ReplyToThreadResponse)
def reply_to_thread(
    thread_id: str,
    payload: ReplyToThreadRequest,
    service: ThreadService = Depends(get_thread_service),
) -> ReplyToThreadResponse:
    try:
        thread, sent_message = service.send_reply(
            thread_id,
            payload.body,
            mute_thread=payload.mute_thread,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ReplyToThreadResponse(
        thread=thread,
        sent_message=sent_message,
        muted=payload.mute_thread,
    )
