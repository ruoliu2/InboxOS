import base64
import json
from datetime import UTC, datetime

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
    ThreadSummary,
    ThreadSummaryPage,
)
from app.services.auth_service import AuthService, LinkedAccountAccess
from app.services.dependencies import (
    get_auth_service,
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

ALL_SCOPE = "all"
THREAD_TOKEN_VERSION = 1
AGGREGATE_TOKEN_VERSION = 1


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


def encode_scoped_thread_id(linked_account_id: str, provider_thread_id: str) -> str:
    payload = json.dumps(
        {
            "v": THREAD_TOKEN_VERSION,
            "linked_account_id": linked_account_id,
            "thread_id": provider_thread_id,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("utf-8").rstrip("=")


def decode_scoped_thread_id(value: str) -> tuple[str, str] | None:
    try:
        padding = "=" * (-len(value) % 4)
        payload = base64.urlsafe_b64decode(f"{value}{padding}".encode())
        parsed = json.loads(payload.decode("utf-8"))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(parsed, dict) or parsed.get("v") != THREAD_TOKEN_VERSION:
        return None
    linked_account_id = str(parsed.get("linked_account_id") or "").strip()
    thread_id = str(parsed.get("thread_id") or "").strip()
    if not linked_account_id or not thread_id:
        return None
    return linked_account_id, thread_id


def serialize_aggregate_page_token(
    *,
    mailbox: MailboxKey,
    unread_only: bool,
    query: str | None,
    total_count: int | None,
    account_tokens: list[dict[str, str | None]],
    leftovers: list[ThreadSummary],
) -> str:
    payload = json.dumps(
        {
            "v": AGGREGATE_TOKEN_VERSION,
            "mailbox": mailbox.value,
            "unread_only": unread_only,
            "query": query,
            "total_count": total_count,
            "account_tokens": account_tokens,
            "leftovers": [thread.model_dump(mode="json") for thread in leftovers],
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("utf-8").rstrip("=")


def deserialize_aggregate_page_token(
    value: str,
) -> tuple[list[dict[str, str | None]], list[ThreadSummary], int | None]:
    try:
        padding = "=" * (-len(value) % 4)
        payload = base64.urlsafe_b64decode(f"{value}{padding}".encode())
        parsed = json.loads(payload.decode("utf-8"))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(
            status_code=422, detail="Invalid aggregate page token."
        ) from exc

    if not isinstance(parsed, dict) or parsed.get("v") != AGGREGATE_TOKEN_VERSION:
        raise HTTPException(status_code=422, detail="Invalid aggregate page token.")

    token_rows = parsed.get("account_tokens") or []
    leftovers = parsed.get("leftovers") or []
    if not isinstance(token_rows, list) or not isinstance(leftovers, list):
        raise HTTPException(status_code=422, detail="Invalid aggregate page token.")

    return (
        [
            {
                "linked_account_id": str(item.get("linked_account_id") or "").strip(),
                "next_page_token": (
                    str(item.get("next_page_token") or "").strip() or None
                ),
            }
            for item in token_rows
            if str(item.get("linked_account_id") or "").strip()
        ],
        [ThreadSummary.model_validate(item) for item in leftovers],
        parsed.get("total_count"),
    )


def sum_optional_counts(values: list[int | None]) -> int | None:
    numeric = [value for value in values if value is not None]
    if not numeric:
        return None
    return sum(numeric)


def sort_threads(threads: list[ThreadSummary]) -> list[ThreadSummary]:
    return sorted(threads, key=lambda item: item.last_message_at, reverse=True)


def with_account_metadata(
    thread: ThreadSummary | ThreadDetail,
    access: LinkedAccountAccess,
) -> ThreadSummary | ThreadDetail:
    payload = thread.model_dump()
    payload["id"] = encode_scoped_thread_id(access.account.id, thread.id)
    payload["linked_account_id"] = access.account.id
    payload["account_email"] = access.account.provider_account_ref
    payload["account_name"] = access.account.display_name
    if isinstance(thread, ThreadDetail):
        return ThreadDetail(**payload)
    return ThreadSummary(**payload)


def resolve_gmail_accounts_for_scope(
    scope: str,
    session: AuthSessionRecord,
    service: AuthService,
) -> list[LinkedAccountAccess]:
    if not session.user_id:
        raise HTTPException(status_code=401, detail="Authentication required.")

    normalized_scope = (scope or ALL_SCOPE).strip() or ALL_SCOPE
    if normalized_scope == ALL_SCOPE:
        accounts = service.list_active_account_access(
            session.user_id,
            provider="google_gmail",
        )
        if not accounts:
            raise HTTPException(
                status_code=404,
                detail="No active linked Google accounts are available.",
            )
        return accounts

    access = service.get_linked_account_access(session.user_id, normalized_scope)
    if access is None or access.account.provider != "google_gmail":
        raise HTTPException(status_code=404, detail="Linked Google account not found.")
    return [access]


def resolve_thread_target(
    scoped_thread_id: str,
    session: AuthSessionRecord,
    service: AuthService,
) -> tuple[LinkedAccountAccess, str]:
    decoded = decode_scoped_thread_id(scoped_thread_id)
    if decoded is not None:
        linked_account_id, provider_thread_id = decoded
        access = service.get_linked_account_access(
            session.user_id or "", linked_account_id
        )
        if access is None or access.account.provider != "google_gmail":
            raise HTTPException(
                status_code=404, detail="Linked Google account not found."
            )
        return access, provider_thread_id

    if not session.active_linked_account_id or not session.user_id:
        raise HTTPException(status_code=422, detail="Invalid Gmail thread id.")

    access = service.get_linked_account_access(
        session.user_id,
        session.active_linked_account_id,
    )
    if access is None or access.account.provider != "google_gmail":
        raise HTTPException(status_code=404, detail="Linked Google account not found.")
    return access, scoped_thread_id


def persist_threads(
    session: AuthSessionRecord,
    store: ConversationStore,
    linked_account_id: str,
    provider: str,
    threads: list[ThreadSummary | ThreadDetail],
    *,
    source_folder: str | None,
) -> None:
    if not session.user_id:
        return

    for thread in threads:
        existing = store.get_by_external_id(
            session.user_id,
            linked_account_id,
            thread.id,
        )
        conversation = existing or new_conversation_record(
            user_id=session.user_id,
            linked_account_id=linked_account_id,
            provider=provider,
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


def list_threads_for_account(
    *,
    access: LinkedAccountAccess,
    background_tasks: BackgroundTasks,
    page_token: str | None,
    page_size: int,
    mailbox: MailboxKey,
    unread_only: bool,
    query: str | None,
    client: GoogleWorkspaceClient,
    cache: GmailMailboxCache,
    session: AuthSessionRecord,
    conversation_store: ConversationStore,
) -> ThreadSummaryPage:
    if page_token is None and query is None:
        cached_page = cache.get_thread_page(
            access.account.provider_account_ref or "",
            mailbox_key=mailbox.value,
            unread_only=unread_only,
            query=query,
            page_key=None,
        )
        if cached_page is not None:
            persist_threads(
                session,
                conversation_store,
                access.account.id,
                access.account.provider,
                cached_page.threads,
                source_folder=mailbox.value,
            )
            background_tasks.add_task(
                refresh_gmail_thread_page_cache,
                access.account.provider_account_ref or "",
                access.credential.access_token,
                page_size,
                mailbox,
                unread_only,
                query,
                client,
                cache,
            )
            return ThreadSummaryPage(
                threads=[
                    with_account_metadata(thread, access)
                    for thread in cached_page.threads
                ],
                next_page_token=cached_page.next_page_token,
                has_more=cached_page.has_more,
                total_count=cached_page.total_count,
            )

    try:
        page = client.list_gmail_threads(
            access.credential.access_token,
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
        access.account.provider_account_ref or "",
        page=page,
        mailbox_key=mailbox.value,
        unread_only=unread_only,
        query=query,
        page_key=page_token,
    )
    persist_threads(
        session,
        conversation_store,
        access.account.id,
        access.account.provider,
        page.threads,
        source_folder=mailbox.value,
    )
    return ThreadSummaryPage(
        threads=[with_account_metadata(thread, access) for thread in page.threads],
        next_page_token=page.next_page_token,
        has_more=page.has_more,
        total_count=page.total_count,
    )


def list_threads_for_all_accounts(
    *,
    accounts: list[LinkedAccountAccess],
    page_token: str | None,
    page_size: int,
    mailbox: MailboxKey,
    unread_only: bool,
    query: str | None,
    client: GoogleWorkspaceClient,
) -> ThreadSummaryPage:
    account_map = {account.account.id: account for account in accounts}
    if page_token is None:
        aggregate_threads: list[ThreadSummary] = []
        account_tokens: list[dict[str, str | None]] = []
        total_count = 0
        saw_total = False
        for access in accounts:
            try:
                page = client.list_gmail_threads(
                    access.credential.access_token,
                    max_results=page_size,
                    mailbox=mailbox,
                    unread_only=unread_only,
                    query=query,
                )
            except GoogleAPIError as exc:
                raise HTTPException(
                    status_code=exc.app_status_code,
                    detail=str(exc),
                ) from exc
            except RuntimeError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            aggregate_threads.extend(
                [with_account_metadata(thread, access) for thread in page.threads]
            )
            account_tokens.append(
                {
                    "linked_account_id": access.account.id,
                    "next_page_token": page.next_page_token,
                }
            )
            if page.total_count is not None:
                total_count += page.total_count
                saw_total = True

        sorted_threads = sort_threads(aggregate_threads)
        visible_threads = sorted_threads[:page_size]
        leftovers = sorted_threads[page_size:]
        has_more = bool(leftovers) or any(
            item["next_page_token"] for item in account_tokens
        )
        return ThreadSummaryPage(
            threads=visible_threads,
            next_page_token=(
                serialize_aggregate_page_token(
                    mailbox=mailbox,
                    unread_only=unread_only,
                    query=query,
                    total_count=total_count if saw_total else None,
                    account_tokens=account_tokens,
                    leftovers=leftovers,
                )
                if has_more
                else None
            ),
            has_more=has_more,
            total_count=total_count if saw_total else None,
        )

    account_tokens, leftovers, total_count = deserialize_aggregate_page_token(
        page_token
    )
    pool = list(leftovers)
    while len(pool) < page_size and any(
        item["next_page_token"] for item in account_tokens
    ):
        next_batch: list[ThreadSummary] = []
        for item in account_tokens:
            next_cursor = item["next_page_token"]
            if not next_cursor:
                continue
            access = account_map.get(item["linked_account_id"] or "")
            if access is None:
                continue
            try:
                page = client.list_gmail_threads(
                    access.credential.access_token,
                    max_results=page_size,
                    page_token=next_cursor,
                    mailbox=mailbox,
                    unread_only=unread_only,
                    query=query,
                )
            except GoogleAPIError as exc:
                raise HTTPException(
                    status_code=exc.app_status_code,
                    detail=str(exc),
                ) from exc
            except RuntimeError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            next_batch.extend(
                [with_account_metadata(thread, access) for thread in page.threads]
            )
            item["next_page_token"] = page.next_page_token
        if not next_batch:
            break
        pool = sort_threads(pool + next_batch)

    visible_threads = pool[:page_size]
    next_leftovers = pool[page_size:]
    has_more = bool(next_leftovers) or any(
        item["next_page_token"] for item in account_tokens
    )
    return ThreadSummaryPage(
        threads=visible_threads,
        next_page_token=(
            serialize_aggregate_page_token(
                mailbox=mailbox,
                unread_only=unread_only,
                query=query,
                total_count=total_count,
                account_tokens=account_tokens,
                leftovers=next_leftovers,
            )
            if has_more
            else None
        ),
        has_more=has_more,
        total_count=total_count,
    )


@router.get("/threads", response_model=ThreadSummaryPage)
def list_gmail_threads(
    background_tasks: BackgroundTasks,
    page_token: str | None = Query(default=None),
    page_size: int = Query(default=20, ge=1, le=50),
    mailbox: MailboxKey = Query(default=MailboxKey.INBOX),
    unread_only: bool = Query(default=False),
    q: str | None = Query(default=None),
    scope: str = Query(default=ALL_SCOPE),
    session: AuthSessionRecord = Depends(get_current_auth_session),
    auth_service: AuthService = Depends(get_auth_service),
    client: GoogleWorkspaceClient = Depends(get_google_workspace_client),
    cache: GmailMailboxCache = Depends(get_gmail_mailbox_cache),
    conversation_store: ConversationStore = Depends(get_conversation_store),
) -> ThreadSummaryPage:
    query = (q or "").strip() or None
    accounts = resolve_gmail_accounts_for_scope(scope, session, auth_service)
    if len(accounts) == 1:
        return list_threads_for_account(
            access=accounts[0],
            background_tasks=background_tasks,
            page_token=page_token,
            page_size=page_size,
            mailbox=mailbox,
            unread_only=unread_only,
            query=query,
            client=client,
            cache=cache,
            session=session,
            conversation_store=conversation_store,
        )

    page = list_threads_for_all_accounts(
        accounts=accounts,
        page_token=page_token,
        page_size=page_size,
        mailbox=mailbox,
        unread_only=unread_only,
        query=query,
        client=client,
    )
    for thread in page.threads:
        if not thread.linked_account_id or not thread.id:
            continue
        raw_thread_id = decode_scoped_thread_id(thread.id)
        if raw_thread_id is None:
            continue
        linked_account_id, provider_thread_id = raw_thread_id
        access = next(
            (item for item in accounts if item.account.id == linked_account_id),
            None,
        )
        if access is None:
            continue
        persist_threads(
            session,
            conversation_store,
            access.account.id,
            access.account.provider,
            [ThreadSummary(**{**thread.model_dump(), "id": provider_thread_id})],
            source_folder=mailbox.value,
        )
    return page


@router.get("/mailbox-counts", response_model=MailboxCountsResponse)
def get_gmail_mailbox_counts(
    scope: str = Query(default=ALL_SCOPE),
    session: AuthSessionRecord = Depends(get_current_auth_session),
    auth_service: AuthService = Depends(get_auth_service),
    client: GoogleWorkspaceClient = Depends(get_google_workspace_client),
) -> MailboxCountsResponse:
    accounts = resolve_gmail_accounts_for_scope(scope, session, auth_service)

    counts_by_account: list[MailboxCountsResponse] = []
    for access in accounts:
        try:
            counts_by_account.append(
                client.get_gmail_mailbox_counts(access.credential.access_token)
            )
        except GoogleAPIError as exc:
            raise HTTPException(
                status_code=exc.app_status_code, detail=str(exc)
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    if len(counts_by_account) == 1 and (scope or ALL_SCOPE) != ALL_SCOPE:
        return counts_by_account[0]

    return MailboxCountsResponse(
        inbox=sum_optional_counts([item.inbox for item in counts_by_account]),
        sent=sum_optional_counts([item.sent for item in counts_by_account]),
        archive=sum_optional_counts([item.archive for item in counts_by_account]),
        trash=sum_optional_counts([item.trash for item in counts_by_account]),
        junk=sum_optional_counts([item.junk for item in counts_by_account]),
    )


@router.get("/threads/{thread_id}", response_model=ThreadDetail)
def get_gmail_thread(
    thread_id: str,
    session: AuthSessionRecord = Depends(get_current_auth_session),
    auth_service: AuthService = Depends(get_auth_service),
    client: GoogleWorkspaceClient = Depends(get_google_workspace_client),
    cache: GmailMailboxCache = Depends(get_gmail_mailbox_cache),
    conversation_store: ConversationStore = Depends(get_conversation_store),
) -> ThreadDetail:
    access, provider_thread_id = resolve_thread_target(thread_id, session, auth_service)

    cached_thread = cache.get_thread_detail(
        access.account.provider_account_ref or "",
        provider_thread_id,
    )
    if cached_thread is not None:
        persist_threads(
            session,
            conversation_store,
            access.account.id,
            access.account.provider,
            [cached_thread],
            source_folder=None,
        )
        return with_account_metadata(cached_thread, access)

    try:
        thread = client.get_gmail_thread(
            access.credential.access_token, provider_thread_id
        )
    except GoogleAPIError as exc:
        raise HTTPException(status_code=exc.app_status_code, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    cache.upsert_thread_detail(access.account.provider_account_ref or "", thread)
    persist_threads(
        session,
        conversation_store,
        access.account.id,
        access.account.provider,
        [thread],
        source_folder=None,
    )
    return with_account_metadata(thread, access)


@router.post("/threads/{thread_id}/reply", response_model=ReplyToThreadResponse)
def reply_to_gmail_thread(
    thread_id: str,
    payload: ReplyToThreadRequest,
    session: AuthSessionRecord = Depends(get_current_auth_session),
    auth_service: AuthService = Depends(get_auth_service),
    client: GoogleWorkspaceClient = Depends(get_google_workspace_client),
    cache: GmailMailboxCache = Depends(get_gmail_mailbox_cache),
    conversation_store: ConversationStore = Depends(get_conversation_store),
) -> ReplyToThreadResponse:
    access, provider_thread_id = resolve_thread_target(thread_id, session, auth_service)

    try:
        result = client.compose_gmail_thread(
            access.credential.access_token,
            account_email=access.account.provider_account_ref or "",
            thread_id=provider_thread_id,
            payload=ComposeThreadRequest(body=payload.body),
        )
    except GoogleAPIError as exc:
        raise HTTPException(status_code=exc.app_status_code, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    cache.invalidate_account_pages(access.account.provider_account_ref or "")
    cache.upsert_thread_detail(access.account.provider_account_ref or "", result.thread)
    persist_threads(
        session,
        conversation_store,
        access.account.id,
        access.account.provider,
        [result.thread],
        source_folder=None,
    )
    return ReplyToThreadResponse(
        thread=with_account_metadata(result.thread, access),
        sent_message=result.sent_message,
        muted=payload.mute_thread,
    )


@router.post("/threads/{thread_id}/compose", response_model=ComposeThreadResponse)
def compose_gmail_thread(
    thread_id: str,
    payload: ComposeThreadRequest,
    session: AuthSessionRecord = Depends(get_current_auth_session),
    auth_service: AuthService = Depends(get_auth_service),
    client: GoogleWorkspaceClient = Depends(get_google_workspace_client),
    cache: GmailMailboxCache = Depends(get_gmail_mailbox_cache),
    conversation_store: ConversationStore = Depends(get_conversation_store),
) -> ComposeThreadResponse:
    access, provider_thread_id = resolve_thread_target(thread_id, session, auth_service)

    try:
        result = client.compose_gmail_thread(
            access.credential.access_token,
            account_email=access.account.provider_account_ref or "",
            thread_id=provider_thread_id,
            payload=payload,
        )
    except GoogleAPIError as exc:
        raise HTTPException(status_code=exc.app_status_code, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    cache.invalidate_account_pages(access.account.provider_account_ref or "")
    cache.upsert_thread_detail(access.account.provider_account_ref or "", result.thread)
    persist_threads(
        session,
        conversation_store,
        access.account.id,
        access.account.provider,
        [result.thread],
        source_folder=None,
    )
    return ComposeThreadResponse(
        thread=with_account_metadata(result.thread, access),
        sent_message=result.sent_message,
        mode=payload.mode,
    )


@router.post("/threads/{thread_id}/action", response_model=ThreadActionResponse)
def act_on_gmail_thread(
    thread_id: str,
    payload: ThreadActionRequest,
    session: AuthSessionRecord = Depends(get_current_auth_session),
    auth_service: AuthService = Depends(get_auth_service),
    client: GoogleWorkspaceClient = Depends(get_google_workspace_client),
    cache: GmailMailboxCache = Depends(get_gmail_mailbox_cache),
    conversation_store: ConversationStore = Depends(get_conversation_store),
) -> ThreadActionResponse:
    access, provider_thread_id = resolve_thread_target(thread_id, session, auth_service)

    try:
        result = client.apply_gmail_thread_action(
            access.credential.access_token,
            thread_id=provider_thread_id,
            action=payload.action.value,
        )
    except GoogleAPIError as exc:
        raise HTTPException(status_code=exc.app_status_code, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    cache.invalidate_account_pages(access.account.provider_account_ref or "")
    if result.thread is None:
        cache.delete_thread_detail(
            access.account.provider_account_ref or "",
            provider_thread_id,
        )
        scoped_result_thread = None
    else:
        cache.upsert_thread_detail(
            access.account.provider_account_ref or "",
            result.thread,
        )
        persist_threads(
            session,
            conversation_store,
            access.account.id,
            access.account.provider,
            [result.thread],
            source_folder=None,
        )
        scoped_result_thread = with_account_metadata(result.thread, access)

    return ThreadActionResponse(
        thread_id=encode_scoped_thread_id(access.account.id, provider_thread_id),
        action=payload.action,
        thread=scoped_result_thread,
        deleted=result.deleted,
    )
