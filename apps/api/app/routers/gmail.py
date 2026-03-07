from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from app.integrations.google_workspace import GoogleAPIError, GoogleWorkspaceClient
from app.schemas.thread import (
    ComposeThreadRequest,
    ComposeThreadResponse,
    MailboxCountsResponse,
    MailboxKey,
    ReplyToThreadRequest,
    ReplyToThreadResponse,
    ThreadActionRequest,
    ThreadActionResponse,
    ThreadDetail,
    ThreadSummaryPage,
)
from app.services.dependencies import (
    get_current_auth_session,
    get_gmail_mailbox_cache,
    get_google_workspace_client,
)
from app.storage.auth_store import AuthSessionRecord
from app.storage.mailbox_cache import GmailMailboxCache

router = APIRouter()


def refresh_gmail_thread_page_cache(
    account_email: str,
    access_token: str,
    page_size: int,
    mailbox: MailboxKey,
    unread_only: bool,
    query: str | None,
    client: GoogleWorkspaceClient,
    cache: GmailMailboxCache,
) -> None:
    try:
        page = client.list_gmail_threads(
            access_token,
            max_results=page_size,
            mailbox=mailbox,
            unread_only=unread_only,
            query=query,
        )
    except RuntimeError:
        return
    cache.store_thread_page(
        account_email,
        page=page,
        mailbox_key=mailbox.value,
        unread_only=unread_only,
        query=query,
        page_key=None,
    )


@router.get("/threads", response_model=ThreadSummaryPage)
def list_gmail_threads(
    background_tasks: BackgroundTasks,
    page_token: str | None = Query(default=None),
    page_size: int = Query(default=20, ge=1, le=50),
    mailbox: MailboxKey = Query(default=MailboxKey.INBOX),
    unread_only: bool = Query(default=False),
    q: str | None = Query(default=None),
    session: AuthSessionRecord = Depends(get_current_auth_session),
    client: GoogleWorkspaceClient = Depends(get_google_workspace_client),
    cache: GmailMailboxCache = Depends(get_gmail_mailbox_cache),
) -> ThreadSummaryPage:
    query = (q or "").strip() or None

    if page_token is None and query is None:
        cached_page = cache.get_thread_page(
            session.account_email,
            mailbox_key=mailbox.value,
            unread_only=unread_only,
            query=query,
            page_key=None,
        )
        if cached_page is not None:
            background_tasks.add_task(
                refresh_gmail_thread_page_cache,
                session.account_email,
                session.access_token,
                page_size,
                mailbox,
                unread_only,
                query,
                client,
                cache,
            )
            return cached_page

    try:
        page = client.list_gmail_threads(
            session.access_token,
            max_results=page_size,
            page_token=page_token,
            mailbox=mailbox,
            unread_only=unread_only,
            query=query,
        )
    except GoogleAPIError as exc:
        raise HTTPException(status_code=exc.app_status_code, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    cache.store_thread_page(
        session.account_email,
        page=page,
        mailbox_key=mailbox.value,
        unread_only=unread_only,
        query=query,
        page_key=page_token,
    )
    return page


@router.get("/mailbox-counts", response_model=MailboxCountsResponse)
def get_gmail_mailbox_counts(
    session: AuthSessionRecord = Depends(get_current_auth_session),
    client: GoogleWorkspaceClient = Depends(get_google_workspace_client),
) -> MailboxCountsResponse:
    try:
        return client.get_gmail_mailbox_counts(session.access_token)
    except GoogleAPIError as exc:
        raise HTTPException(status_code=exc.app_status_code, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/threads/{thread_id}", response_model=ThreadDetail)
def get_gmail_thread(
    thread_id: str,
    session: AuthSessionRecord = Depends(get_current_auth_session),
    client: GoogleWorkspaceClient = Depends(get_google_workspace_client),
    cache: GmailMailboxCache = Depends(get_gmail_mailbox_cache),
) -> ThreadDetail:
    try:
        thread = client.get_gmail_thread(session.access_token, thread_id)
    except GoogleAPIError as exc:
        raise HTTPException(status_code=exc.app_status_code, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    cache.upsert_thread_detail(session.account_email, thread)
    return thread


@router.post("/threads/{thread_id}/reply", response_model=ReplyToThreadResponse)
def reply_to_gmail_thread(
    thread_id: str,
    payload: ReplyToThreadRequest,
    session: AuthSessionRecord = Depends(get_current_auth_session),
    client: GoogleWorkspaceClient = Depends(get_google_workspace_client),
    cache: GmailMailboxCache = Depends(get_gmail_mailbox_cache),
) -> ReplyToThreadResponse:
    try:
        result = client.compose_gmail_thread(
            session.access_token,
            account_email=session.account_email,
            thread_id=thread_id,
            payload=ComposeThreadRequest(body=payload.body),
        )
    except GoogleAPIError as exc:
        raise HTTPException(status_code=exc.app_status_code, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    cache.invalidate_account_pages(session.account_email)
    cache.upsert_thread_detail(session.account_email, result.thread)
    return ReplyToThreadResponse(
        thread=result.thread,
        sent_message=result.sent_message,
        muted=payload.mute_thread,
    )


@router.post("/threads/{thread_id}/compose", response_model=ComposeThreadResponse)
def compose_gmail_thread(
    thread_id: str,
    payload: ComposeThreadRequest,
    session: AuthSessionRecord = Depends(get_current_auth_session),
    client: GoogleWorkspaceClient = Depends(get_google_workspace_client),
    cache: GmailMailboxCache = Depends(get_gmail_mailbox_cache),
) -> ComposeThreadResponse:
    try:
        result = client.compose_gmail_thread(
            session.access_token,
            account_email=session.account_email,
            thread_id=thread_id,
            payload=payload,
        )
    except GoogleAPIError as exc:
        raise HTTPException(status_code=exc.app_status_code, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    cache.invalidate_account_pages(session.account_email)
    cache.upsert_thread_detail(session.account_email, result.thread)
    return ComposeThreadResponse(
        thread=result.thread,
        sent_message=result.sent_message,
        mode=payload.mode,
    )


@router.post("/threads/{thread_id}/action", response_model=ThreadActionResponse)
def act_on_gmail_thread(
    thread_id: str,
    payload: ThreadActionRequest,
    session: AuthSessionRecord = Depends(get_current_auth_session),
    client: GoogleWorkspaceClient = Depends(get_google_workspace_client),
    cache: GmailMailboxCache = Depends(get_gmail_mailbox_cache),
) -> ThreadActionResponse:
    try:
        result = client.apply_gmail_thread_action(
            session.access_token,
            thread_id=thread_id,
            action=payload.action.value,
        )
    except GoogleAPIError as exc:
        raise HTTPException(status_code=exc.app_status_code, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    cache.invalidate_account_pages(session.account_email)
    if result.thread is None:
        cache.delete_thread_detail(session.account_email, thread_id)
    else:
        cache.upsert_thread_detail(session.account_email, result.thread)

    return ThreadActionResponse(
        thread_id=thread_id,
        action=payload.action,
        thread=result.thread,
        deleted=result.deleted,
    )
