from datetime import UTC, datetime
from mimetypes import guess_type
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
from pydantic import ValidationError

from app.integrations.google_workspace import (
    GmailOutgoingAttachment,
    GoogleAPIError,
    GoogleWorkspaceClient,
)
from app.schemas.thread import (
    ComposeThreadRequest,
    ComposeThreadResponse,
    MailboxCountsResponse,
    MailboxKey,
    ReplyToThreadRequest,
    ReplyToThreadResponse,
    SendGmailMessageRequest,
    SendGmailMessageResponse,
    ThreadActionRequest,
    ThreadActionResponse,
    ThreadDetail,
    ThreadSummary,
    ThreadSummaryPage,
)
from app.services.dependencies import (
    get_conversation_store,
    get_current_auth_session,
    get_gmail_mailbox_cache,
    get_google_workspace_client,
)
from app.storage.auth_store import AuthSessionRecord
from app.storage.conversation_store import (
    ConversationStore,
    build_insight_record,
    new_conversation_record,
)
from app.storage.mailbox_cache import GmailMailboxCache

router = APIRouter()

MAX_GMAIL_MESSAGE_ATTACHMENTS = 10
MAX_GMAIL_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_GMAIL_TOTAL_ATTACHMENT_BYTES = 20 * 1024 * 1024
ATTACHMENT_READ_CHUNK_BYTES = 1024 * 1024


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


def require_active_google_account(session: AuthSessionRecord) -> tuple[str, str]:
    if not session.account_email or not session.access_token:
        raise HTTPException(
            status_code=401,
            detail="An active linked Google account is required.",
        )
    return session.account_email, session.access_token


def persist_threads(
    session: AuthSessionRecord,
    store: ConversationStore,
    threads: list[ThreadSummary | ThreadDetail],
    *,
    source_folder: str | None,
) -> None:
    if (
        not session.user_id
        or not session.active_linked_account_id
        or not session.provider
    ):
        return
    for thread in threads:
        existing = store.get_by_external_id(
            session.user_id,
            session.active_linked_account_id,
            thread.id,
        )
        conversation = existing or new_conversation_record(
            user_id=session.user_id,
            linked_account_id=session.active_linked_account_id,
            provider=session.provider,
            external_conversation_id=thread.id,
            title=thread.subject,
            preview=thread.snippet,
            last_message_at=thread.last_message_at,
            source_folder=source_folder,
        )
        conversation.title = thread.subject
        conversation.preview = thread.snippet
        conversation.last_message_at = thread.last_message_at
        conversation.source_folder = source_folder or conversation.source_folder
        conversation.updated_at = datetime.now(UTC)
        conversation = store.upsert_conversation(conversation)
        store.upsert_insight(
            build_insight_record(
                conversation_id=conversation.id,
                thread=thread,
            )
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
    conversation_store: ConversationStore = Depends(get_conversation_store),
) -> ThreadSummaryPage:
    account_email, access_token = require_active_google_account(session)
    query = (q or "").strip() or None

    if page_token is None and query is None:
        cached_page = cache.get_thread_page(
            account_email,
            mailbox_key=mailbox.value,
            unread_only=unread_only,
            query=query,
            page_key=None,
        )
        if cached_page is not None:
            persist_threads(
                session,
                conversation_store,
                cached_page.threads,
                source_folder=mailbox.value,
            )
            background_tasks.add_task(
                refresh_gmail_thread_page_cache,
                account_email,
                access_token,
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
            access_token,
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
        account_email,
        page=page,
        mailbox_key=mailbox.value,
        unread_only=unread_only,
        query=query,
        page_key=page_token,
    )
    persist_threads(
        session,
        conversation_store,
        page.threads,
        source_folder=mailbox.value,
    )
    return page


@router.get("/mailbox-counts", response_model=MailboxCountsResponse)
def get_gmail_mailbox_counts(
    session: AuthSessionRecord = Depends(get_current_auth_session),
    client: GoogleWorkspaceClient = Depends(get_google_workspace_client),
) -> MailboxCountsResponse:
    _, access_token = require_active_google_account(session)
    try:
        return client.get_gmail_mailbox_counts(access_token)
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
    conversation_store: ConversationStore = Depends(get_conversation_store),
) -> ThreadDetail:
    account_email, access_token = require_active_google_account(session)
    try:
        thread = client.get_gmail_thread(access_token, thread_id)
    except GoogleAPIError as exc:
        raise HTTPException(status_code=exc.app_status_code, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    cache.upsert_thread_detail(account_email, thread)
    persist_threads(
        session,
        conversation_store,
        [thread],
        source_folder=None,
    )
    return thread


@router.post("/threads/{thread_id}/reply", response_model=ReplyToThreadResponse)
def reply_to_gmail_thread(
    thread_id: str,
    payload: ReplyToThreadRequest,
    session: AuthSessionRecord = Depends(get_current_auth_session),
    client: GoogleWorkspaceClient = Depends(get_google_workspace_client),
    cache: GmailMailboxCache = Depends(get_gmail_mailbox_cache),
    conversation_store: ConversationStore = Depends(get_conversation_store),
) -> ReplyToThreadResponse:
    account_email, access_token = require_active_google_account(session)
    try:
        result = client.compose_gmail_thread(
            access_token,
            account_email=account_email,
            thread_id=thread_id,
            payload=ComposeThreadRequest(body=payload.body),
        )
    except GoogleAPIError as exc:
        raise HTTPException(status_code=exc.app_status_code, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    cache.invalidate_account_pages(account_email)
    cache.upsert_thread_detail(account_email, result.thread)
    persist_threads(
        session,
        conversation_store,
        [result.thread],
        source_folder=None,
    )
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
    conversation_store: ConversationStore = Depends(get_conversation_store),
) -> ComposeThreadResponse:
    account_email, access_token = require_active_google_account(session)
    try:
        result = client.compose_gmail_thread(
            access_token,
            account_email=account_email,
            thread_id=thread_id,
            payload=payload,
        )
    except GoogleAPIError as exc:
        raise HTTPException(status_code=exc.app_status_code, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    cache.invalidate_account_pages(account_email)
    cache.upsert_thread_detail(account_email, result.thread)
    persist_threads(
        session,
        conversation_store,
        [result.thread],
        source_folder=None,
    )
    return ComposeThreadResponse(
        thread=result.thread,
        sent_message=result.sent_message,
        mode=payload.mode,
    )


def normalize_media_type(value: str | None) -> str:
    return (value or "").partition(";")[0].strip().lower()


@router.post("/messages/send", response_model=SendGmailMessageResponse)
def send_gmail_message(
    to: Annotated[list[str], Form()],
    subject: Annotated[str, Form()],
    body: Annotated[str, Form()] = "",
    attachments: Annotated[list[UploadFile] | None, File()] = None,
    session: AuthSessionRecord = Depends(get_current_auth_session),
    client: GoogleWorkspaceClient = Depends(get_google_workspace_client),
    cache: GmailMailboxCache = Depends(get_gmail_mailbox_cache),
    conversation_store: ConversationStore = Depends(get_conversation_store),
) -> SendGmailMessageResponse:
    account_email, access_token = require_active_google_account(session)
    try:
        payload = SendGmailMessageRequest.model_validate(
            {
                "to": to,
                "subject": subject,
                "body": body,
            }
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    outgoing_attachments: list[GmailOutgoingAttachment] = []
    total_attachment_bytes = 0
    uploaded_attachments = attachments or []
    if len(uploaded_attachments) > MAX_GMAIL_MESSAGE_ATTACHMENTS:
        raise HTTPException(
            status_code=413,
            detail=(
                f"You can attach up to {MAX_GMAIL_MESSAGE_ATTACHMENTS} images per message."
            ),
        )
    for index, upload in enumerate(uploaded_attachments, start=1):
        try:
            content_type = normalize_media_type(
                upload.content_type or guess_type(upload.filename or "")[0]
            )
            if not content_type.startswith("image/"):
                raise HTTPException(
                    status_code=422,
                    detail=f"{upload.filename or 'Attachment'} must be an image file.",
                )
            chunks: list[bytes] = []
            file_size = 0
            while True:
                chunk = upload.file.read(ATTACHMENT_READ_CHUNK_BYTES)
                if not chunk:
                    break
                file_size += len(chunk)
                if file_size > MAX_GMAIL_ATTACHMENT_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            f"{upload.filename or 'Attachment'} exceeds the "
                            "10 MiB attachment limit."
                        ),
                    )
                if (
                    total_attachment_bytes + file_size
                    > MAX_GMAIL_TOTAL_ATTACHMENT_BYTES
                ):
                    raise HTTPException(
                        status_code=413,
                        detail="Attachments exceed the 20 MiB total size limit.",
                    )
                chunks.append(chunk)

            data = b"".join(chunks)
            if not data:
                raise HTTPException(
                    status_code=422,
                    detail=f"{upload.filename or 'Attachment'} is empty.",
                )

            total_attachment_bytes += file_size
            subtype = content_type.partition("/")[2] or "png"
            outgoing_attachments.append(
                GmailOutgoingAttachment(
                    filename=upload.filename or f"image-{index}.{subtype}",
                    content_type=content_type,
                    data=data,
                )
            )
        finally:
            upload.file.close()

    try:
        result = client.send_gmail_message(
            access_token,
            account_email=account_email,
            payload=payload,
            attachments=outgoing_attachments,
        )
    except GoogleAPIError as exc:
        raise HTTPException(status_code=exc.app_status_code, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    cache.invalidate_account_pages(account_email)
    cache.upsert_thread_detail(account_email, result.thread)
    persist_threads(
        session,
        conversation_store,
        [result.thread],
        source_folder=None,
    )
    return SendGmailMessageResponse(
        thread=result.thread,
        sent_message=result.sent_message,
    )


@router.post("/threads/{thread_id}/action", response_model=ThreadActionResponse)
def act_on_gmail_thread(
    thread_id: str,
    payload: ThreadActionRequest,
    session: AuthSessionRecord = Depends(get_current_auth_session),
    client: GoogleWorkspaceClient = Depends(get_google_workspace_client),
    cache: GmailMailboxCache = Depends(get_gmail_mailbox_cache),
    conversation_store: ConversationStore = Depends(get_conversation_store),
) -> ThreadActionResponse:
    account_email, access_token = require_active_google_account(session)
    try:
        result = client.apply_gmail_thread_action(
            access_token,
            thread_id=thread_id,
            action=payload.action.value,
        )
    except GoogleAPIError as exc:
        raise HTTPException(status_code=exc.app_status_code, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    cache.invalidate_account_pages(account_email)
    if result.thread is None:
        cache.delete_thread_detail(account_email, thread_id)
    else:
        cache.upsert_thread_detail(account_email, result.thread)
        persist_threads(
            session,
            conversation_store,
            [result.thread],
            source_folder=None,
        )

    return ThreadActionResponse(
        thread_id=thread_id,
        action=payload.action,
        thread=result.thread,
        deleted=result.deleted,
    )
