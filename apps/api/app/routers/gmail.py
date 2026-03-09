import base64
import hmac
import json
from datetime import UTC, datetime
from mimetypes import guess_type
from typing import Annotated
from urllib.parse import urlparse

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from pydantic import ValidationError

from app.core.config import get_settings
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
    ThreadHydrateRequest,
    ThreadHydrateResponse,
    ThreadSummary,
    ThreadSummaryPage,
)
from app.services.dependencies import (
    get_conversation_store,
    get_current_auth_session,
    get_gmail_mailbox_cache,
    get_gmail_mailbox_service,
    get_gmail_mailbox_store,
    get_google_workspace_client,
)
from app.services.gmail_mailbox_service import GmailMailboxService
from app.storage.auth_store import AuthSessionRecord
from app.storage.conversation_store import (
    ConversationStore,
    build_insight_record,
    new_conversation_record,
)
from app.storage.gmail_mailbox_store import GmailMailboxStore
from app.storage.mailbox_cache import GmailMailboxCache

router = APIRouter()

MAX_GMAIL_MESSAGE_ATTACHMENTS = 10
MAX_GMAIL_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_GMAIL_TOTAL_ATTACHMENT_BYTES = 20 * 1024 * 1024
ATTACHMENT_READ_CHUNK_BYTES = 1024 * 1024


def require_active_google_account(session: AuthSessionRecord) -> tuple[str, str]:
    if not session.account_email or not session.access_token:
        raise HTTPException(
            status_code=401,
            detail="An active linked Google account is required.",
        )
    return session.account_email, session.access_token


def runtime_error_to_http_exception(exc: RuntimeError) -> HTTPException:
    detail = str(exc)
    normalized = detail.lower()
    if any(
        marker in normalized
        for marker in (
            "active linked google account",
            "linked account not found",
            "provider credentials",
            "google credential expired",
        )
    ):
        return HTTPException(status_code=401, detail=detail)
    return HTTPException(status_code=502, detail=detail)


def request_origin(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value.strip())
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def allowed_write_origins() -> set[str]:
    settings = get_settings()
    origins = {
        origin
        for origin in (
            request_origin(settings.web_base_url),
            *(
                request_origin(item)
                for item in settings.cors_origins.split(",")
                if item.strip()
            ),
        )
        if origin is not None
    }
    return origins


def require_trusted_write_request(request: Request) -> None:
    settings = get_settings()
    if not settings.session_cookie_secure:
        return
    origin = request_origin(request.headers.get("origin"))
    referer_origin = request_origin(request.headers.get("referer"))
    candidate = origin or referer_origin
    if candidate is None or candidate not in allowed_write_origins():
        raise HTTPException(
            status_code=403,
            detail="Cross-site write request rejected.",
        )


def close_uploads(uploads: list[UploadFile]) -> None:
    for upload in uploads:
        try:
            upload.file.close()
        except Exception:
            continue


def to_thread_summary(thread: ThreadDetail) -> ThreadSummary:
    return ThreadSummary(
        id=thread.id,
        subject=thread.subject,
        snippet=thread.snippet,
        participants=thread.participants,
        last_message_at=thread.last_message_at,
        action_states=thread.action_states,
    )


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
    service: GmailMailboxService = Depends(get_gmail_mailbox_service),
    conversation_store: ConversationStore = Depends(get_conversation_store),
) -> ThreadSummaryPage:
    query = (q or "").strip() or None
    cached_page = service.get_cached_thread_page(
        session,
        mailbox=mailbox,
        unread_only=unread_only,
        query=query,
        page_token=page_token,
    )
    if cached_page is not None:
        ready_threads = [
            thread
            for thread in cached_page.threads
            if isinstance(thread, ThreadSummary)
        ]
        if ready_threads:
            persist_threads(
                session,
                conversation_store,
                ready_threads,
                source_folder=mailbox.value,
            )
        background_tasks.add_task(
            service.refresh_thread_page_cache,
            session,
            page_size=page_size,
            mailbox=mailbox,
            unread_only=unread_only,
            query=query,
        )
        return cached_page

    try:
        page = service.list_thread_page(
            session,
            page_size=page_size,
            page_token=page_token,
            mailbox=mailbox,
            unread_only=unread_only,
            query=query,
        )
    except GoogleAPIError as exc:
        raise HTTPException(status_code=exc.app_status_code, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise runtime_error_to_http_exception(exc) from exc

    ready_threads = [
        thread for thread in page.threads if isinstance(thread, ThreadSummary)
    ]
    if ready_threads:
        persist_threads(
            session,
            conversation_store,
            ready_threads,
            source_folder=mailbox.value,
        )
    return page


@router.post("/threads/hydrate", response_model=ThreadHydrateResponse)
def hydrate_gmail_threads(
    payload: ThreadHydrateRequest,
    session: AuthSessionRecord = Depends(get_current_auth_session),
    service: GmailMailboxService = Depends(get_gmail_mailbox_service),
    conversation_store: ConversationStore = Depends(get_conversation_store),
) -> ThreadHydrateResponse:
    try:
        response = service.hydrate_threads(session, payload.thread_ids)
    except GoogleAPIError as exc:
        raise HTTPException(status_code=exc.app_status_code, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise runtime_error_to_http_exception(exc) from exc

    if response.threads:
        persist_threads(
            session,
            conversation_store,
            list(response.threads.values()),
            source_folder=None,
        )
    return response


@router.get("/mailbox-counts", response_model=MailboxCountsResponse)
def get_gmail_mailbox_counts(
    background_tasks: BackgroundTasks,
    session: AuthSessionRecord = Depends(get_current_auth_session),
    service: GmailMailboxService = Depends(get_gmail_mailbox_service),
) -> MailboxCountsResponse:
    cached = service.get_cached_mailbox_counts(session)
    if cached is not None:
        background_tasks.add_task(service.refresh_mailbox_counts_safe, session)
        return cached
    try:
        return service.get_mailbox_counts(session)
    except GoogleAPIError as exc:
        raise HTTPException(status_code=exc.app_status_code, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise runtime_error_to_http_exception(exc) from exc


@router.get("/threads/{thread_id}", response_model=ThreadDetail)
def get_gmail_thread(
    thread_id: str,
    session: AuthSessionRecord = Depends(get_current_auth_session),
    client: GoogleWorkspaceClient = Depends(get_google_workspace_client),
    cache: GmailMailboxCache = Depends(get_gmail_mailbox_cache),
    mailbox_store: GmailMailboxStore = Depends(get_gmail_mailbox_store),
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
    if session.active_linked_account_id:
        mailbox_store.upsert_thread_summaries(
            session.active_linked_account_id,
            [to_thread_summary(thread)],
        )
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
    mailbox_store: GmailMailboxStore = Depends(get_gmail_mailbox_store),
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
    if session.active_linked_account_id:
        mailbox_store.invalidate_account_pages(session.active_linked_account_id)
        mailbox_store.upsert_thread_summaries(
            session.active_linked_account_id,
            [to_thread_summary(result.thread)],
        )
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
    mailbox_store: GmailMailboxStore = Depends(get_gmail_mailbox_store),
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
    if session.active_linked_account_id:
        mailbox_store.invalidate_account_pages(session.active_linked_account_id)
        mailbox_store.upsert_thread_summaries(
            session.active_linked_account_id,
            [to_thread_summary(result.thread)],
        )
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
    request: Request,
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
    require_trusted_write_request(request)
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
    try:
        if len(uploaded_attachments) > MAX_GMAIL_MESSAGE_ATTACHMENTS:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"You can attach up to {MAX_GMAIL_MESSAGE_ATTACHMENTS} images per message."
                ),
            )
        for index, upload in enumerate(uploaded_attachments, start=1):
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
                remaining_file_bytes = MAX_GMAIL_ATTACHMENT_BYTES - file_size
                remaining_total_bytes = (
                    MAX_GMAIL_TOTAL_ATTACHMENT_BYTES
                    - total_attachment_bytes
                    - file_size
                )
                if remaining_file_bytes <= 0:
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            f"{upload.filename or 'Attachment'} exceeds the "
                            "10 MiB attachment limit."
                        ),
                    )
                if remaining_total_bytes <= 0:
                    raise HTTPException(
                        status_code=413,
                        detail="Attachments exceed the 20 MiB total size limit.",
                    )
                max_read_bytes = min(
                    ATTACHMENT_READ_CHUNK_BYTES,
                    remaining_file_bytes,
                    remaining_total_bytes,
                )
                chunk = upload.file.read(max_read_bytes + 1)
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
        close_uploads(uploaded_attachments)

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
    mailbox_store: GmailMailboxStore = Depends(get_gmail_mailbox_store),
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
    if session.active_linked_account_id:
        mailbox_store.invalidate_account_pages(session.active_linked_account_id)

    if result.thread is None:
        cache.delete_thread_detail(account_email, thread_id)
        if session.active_linked_account_id:
            mailbox_store.delete_thread_summaries(
                session.active_linked_account_id,
                [thread_id],
            )
    else:
        cache.upsert_thread_detail(account_email, result.thread)
        if session.active_linked_account_id:
            mailbox_store.upsert_thread_summaries(
                session.active_linked_account_id,
                [to_thread_summary(result.thread)],
            )
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


@router.post("/internal/watch")
async def gmail_watch_notification(
    request: Request,
    service: GmailMailboxService = Depends(get_gmail_mailbox_service),
) -> dict[str, bool]:
    expected_token = (get_settings().gmail_watch_pubsub_token or "").strip()
    if not expected_token:
        raise HTTPException(
            status_code=503,
            detail="Gmail watch token is not configured.",
        )
    auth_header = request.headers.get("authorization", "")
    bearer = auth_header.removeprefix("Bearer ").strip() if auth_header else ""
    if not hmac.compare_digest(bearer, expected_token):
        raise HTTPException(status_code=401, detail="Invalid Gmail watch token.")

    payload = await request.json()
    message = payload.get("message", {}) if isinstance(payload, dict) else {}
    encoded = str(message.get("data") or "").strip()
    if not encoded:
        return {"accepted": True}

    padded = encoded + "=" * (-len(encoded) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8")
        notification = json.loads(decoded)
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid Gmail watch payload.",
        ) from exc

    account_email = str(notification.get("emailAddress") or "").strip().lower()
    history_id = str(notification.get("historyId") or "").strip() or None
    if account_email:
        try:
            service.handle_watch_notification(account_email, history_id)
        except GoogleAPIError as exc:
            raise HTTPException(
                status_code=exc.app_status_code, detail=str(exc)
            ) from exc
        except RuntimeError as exc:
            raise runtime_error_to_http_exception(exc) from exc
    return {"accepted": True}
