from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from app.integrations.google_workspace import GoogleAPIError, GoogleWorkspaceClient
from app.schemas.common import ActionState
from app.schemas.thread import (
    ActionViewCountsResponse,
    ComposeThreadRequest,
    ComposeThreadResponse,
    MailboxCountsResponse,
    MailboxKey,
    ReplyToThreadRequest,
    ReplyToThreadResponse,
    ThreadActionRequest,
    ThreadActionResponse,
    ThreadAnalysis,
    ThreadDetail,
    ThreadSummary,
    ThreadSummaryPage,
)
from app.services.dependencies import (
    get_conversation_store,
    get_current_auth_session,
    get_gmail_mailbox_cache,
    get_google_workspace_client,
    get_thread_analysis_service,
)
from app.services.thread_analysis_service import ThreadAnalysisService
from app.storage.auth_store import AuthSessionRecord
from app.storage.conversation_store import (
    ConversationInsightRecord,
    ConversationStore,
    build_insight_record,
    new_conversation_record,
)
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
        conversation.metadata = {
            **conversation.metadata,
            "participants": list(thread.participants),
        }
        conversation.updated_at = datetime.now(UTC)
        conversation = store.upsert_conversation(conversation)
        if getattr(thread, "analysis", None) is not None:
            store.upsert_insight(
                build_insight_record(
                    conversation_id=conversation.id,
                    thread=thread,
                )
            )


def build_thread_analysis_from_insight(
    insight: ConversationInsightRecord | None,
) -> ThreadAnalysis | None:
    if insight is None or insight.analyzed_at is None:
        return None
    if insight.summary is None or insight.recommended_next_action is None:
        return None
    return ThreadAnalysis(
        summary=insight.summary,
        action_items=list(insight.action_items),
        deadlines=list(insight.deadlines),
        extracted_tasks=list(insight.extracted_tasks),
        requested_items=list(insight.requested_items),
        recommended_next_action=insight.recommended_next_action,
        action_states=[ActionState(state) for state in insight.action_states],
        analyzed_at=insight.analyzed_at,
    )


def hydrate_thread_summary(
    session: AuthSessionRecord,
    store: ConversationStore,
    thread: ThreadSummary,
) -> ThreadSummary:
    if not session.user_id or not session.active_linked_account_id:
        return thread
    insight = store.get_insight_by_external_id(
        session.user_id,
        session.active_linked_account_id,
        thread.id,
    )
    if insight and insight.action_states:
        thread.action_states = [ActionState(state) for state in insight.action_states]
    return thread


def hydrate_thread_detail(
    session: AuthSessionRecord,
    store: ConversationStore,
    thread: ThreadDetail,
) -> tuple[ThreadDetail, ConversationInsightRecord | None]:
    if not session.user_id or not session.active_linked_account_id:
        return thread, None
    insight = store.get_insight_by_external_id(
        session.user_id,
        session.active_linked_account_id,
        thread.id,
    )
    analysis_payload = build_thread_analysis_from_insight(insight)
    if analysis_payload is not None:
        thread.analysis = analysis_payload
        thread.action_states = list(thread.analysis.action_states)
    elif insight and insight.action_states:
        thread.action_states = [ActionState(state) for state in insight.action_states]
    return thread, insight


def insight_is_stale(
    insight: ConversationInsightRecord | None,
    last_message_at: datetime,
) -> bool:
    return (
        insight is None
        or insight.analyzed_at is None
        or insight.analyzed_at < last_message_at
    )


def analyze_thread_in_background(
    *,
    session: AuthSessionRecord,
    thread_id: str,
    account_email: str,
    access_token: str,
    client: GoogleWorkspaceClient,
    cache: GmailMailboxCache,
    conversation_store: ConversationStore,
    analysis_service: ThreadAnalysisService,
) -> None:
    if (
        not session.user_id
        or not session.active_linked_account_id
        or not session.provider
        or not analysis_service.enabled
    ):
        return
    try:
        thread = client.get_gmail_thread(access_token, thread_id)
        persist_threads(session, conversation_store, [thread], source_folder=None)
        thread, insight = hydrate_thread_detail(session, conversation_store, thread)
        if not insight_is_stale(insight, thread.last_message_at):
            cache.upsert_thread_detail(account_email, thread)
            return
        thread = analysis_service.analyze_thread(
            user_id=session.user_id,
            linked_account_id=session.active_linked_account_id,
            provider=session.provider,
            thread=thread,
        )
        cache.upsert_thread_detail(account_email, thread)
    except (GoogleAPIError, RuntimeError, TimeoutError):
        return


def queue_analysis_for_threads(
    background_tasks: BackgroundTasks,
    *,
    session: AuthSessionRecord,
    thread_ids: list[str],
    account_email: str,
    access_token: str,
    client: GoogleWorkspaceClient,
    cache: GmailMailboxCache,
    conversation_store: ConversationStore,
    analysis_service: ThreadAnalysisService,
) -> None:
    if (
        not thread_ids
        or not session.user_id
        or not session.active_linked_account_id
        or not session.provider
        or not analysis_service.enabled
    ):
        return
    for thread_id in thread_ids:
        background_tasks.add_task(
            analyze_thread_in_background,
            session=session,
            thread_id=thread_id,
            account_email=account_email,
            access_token=access_token,
            client=client,
            cache=cache,
            conversation_store=conversation_store,
            analysis_service=analysis_service,
        )


@router.get("/threads", response_model=ThreadSummaryPage)
def list_gmail_threads(
    background_tasks: BackgroundTasks,
    page_token: str | None = Query(default=None),
    page_size: int = Query(default=20, ge=1, le=50),
    mailbox: MailboxKey = Query(default=MailboxKey.INBOX),
    unread_only: bool = Query(default=False),
    action_state: ActionState | None = Query(default=None),
    q: str | None = Query(default=None),
    session: AuthSessionRecord = Depends(get_current_auth_session),
    client: GoogleWorkspaceClient = Depends(get_google_workspace_client),
    cache: GmailMailboxCache = Depends(get_gmail_mailbox_cache),
    conversation_store: ConversationStore = Depends(get_conversation_store),
    analysis_service: ThreadAnalysisService = Depends(get_thread_analysis_service),
) -> ThreadSummaryPage:
    account_email, access_token = require_active_google_account(session)
    query = (q or "").strip() or None
    if action_state is not None:
        if not session.user_id or not session.active_linked_account_id:
            return ThreadSummaryPage(threads=[], next_page_token=None, has_more=False)
        threads = conversation_store.list_thread_summaries_by_action_state(
            session.user_id,
            session.active_linked_account_id,
            action_state.value,
            limit=page_size,
            query=query,
        )
        return ThreadSummaryPage(
            threads=threads,
            next_page_token=None,
            has_more=False,
            total_count=len(threads),
        )

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
            queue_analysis_for_threads(
                background_tasks,
                session=session,
                thread_ids=[thread.id for thread in cached_page.threads],
                account_email=account_email,
                access_token=access_token,
                client=client,
                cache=cache,
                conversation_store=conversation_store,
                analysis_service=analysis_service,
            )
            return ThreadSummaryPage(
                threads=[
                    hydrate_thread_summary(session, conversation_store, thread)
                    for thread in cached_page.threads
                ],
                next_page_token=cached_page.next_page_token,
                has_more=cached_page.has_more,
                total_count=cached_page.total_count,
            )

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
    queue_analysis_for_threads(
        background_tasks,
        session=session,
        thread_ids=[thread.id for thread in page.threads],
        account_email=account_email,
        access_token=access_token,
        client=client,
        cache=cache,
        conversation_store=conversation_store,
        analysis_service=analysis_service,
    )
    return ThreadSummaryPage(
        threads=[
            hydrate_thread_summary(session, conversation_store, thread)
            for thread in page.threads
        ],
        next_page_token=page.next_page_token,
        has_more=page.has_more,
        total_count=page.total_count,
    )


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


@router.get("/action-counts", response_model=ActionViewCountsResponse)
def get_gmail_action_counts(
    session: AuthSessionRecord = Depends(get_current_auth_session),
    conversation_store: ConversationStore = Depends(get_conversation_store),
) -> ActionViewCountsResponse:
    if not session.user_id or not session.active_linked_account_id:
        return ActionViewCountsResponse()
    counts = conversation_store.count_action_states(
        session.user_id,
        session.active_linked_account_id,
    )
    return ActionViewCountsResponse(
        to_reply=counts.get(ActionState.TO_REPLY.value, 0),
        to_follow_up=counts.get(ActionState.TO_FOLLOW_UP.value, 0),
    )


@router.get("/threads/{thread_id}", response_model=ThreadDetail)
def get_gmail_thread(
    thread_id: str,
    background_tasks: BackgroundTasks,
    session: AuthSessionRecord = Depends(get_current_auth_session),
    client: GoogleWorkspaceClient = Depends(get_google_workspace_client),
    cache: GmailMailboxCache = Depends(get_gmail_mailbox_cache),
    conversation_store: ConversationStore = Depends(get_conversation_store),
    analysis_service: ThreadAnalysisService = Depends(get_thread_analysis_service),
) -> ThreadDetail:
    account_email, access_token = require_active_google_account(session)
    try:
        thread = client.get_gmail_thread(access_token, thread_id)
    except GoogleAPIError as exc:
        raise HTTPException(status_code=exc.app_status_code, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    persist_threads(
        session,
        conversation_store,
        [thread],
        source_folder=None,
    )
    thread, insight = hydrate_thread_detail(session, conversation_store, thread)
    if (
        session.user_id
        and session.active_linked_account_id
        and session.provider
        and analysis_service.enabled
        and insight_is_stale(insight, thread.last_message_at)
    ):
        try:
            thread = analysis_service.analyze_thread(
                user_id=session.user_id,
                linked_account_id=session.active_linked_account_id,
                provider=session.provider,
                thread=thread,
                timeout_seconds=3.0,
            )
        except TimeoutError:
            background_tasks.add_task(
                analyze_thread_in_background,
                session=session,
                thread_id=thread_id,
                account_email=account_email,
                access_token=access_token,
                client=client,
                cache=cache,
                conversation_store=conversation_store,
                analysis_service=analysis_service,
            )
        except RuntimeError:
            pass
    cache.upsert_thread_detail(account_email, thread)
    return thread


@router.post("/threads/{thread_id}/reply", response_model=ReplyToThreadResponse)
def reply_to_gmail_thread(
    thread_id: str,
    payload: ReplyToThreadRequest,
    background_tasks: BackgroundTasks,
    session: AuthSessionRecord = Depends(get_current_auth_session),
    client: GoogleWorkspaceClient = Depends(get_google_workspace_client),
    cache: GmailMailboxCache = Depends(get_gmail_mailbox_cache),
    conversation_store: ConversationStore = Depends(get_conversation_store),
    analysis_service: ThreadAnalysisService = Depends(get_thread_analysis_service),
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
    background_tasks.add_task(
        analyze_thread_in_background,
        session=session,
        thread_id=thread_id,
        account_email=account_email,
        access_token=access_token,
        client=client,
        cache=cache,
        conversation_store=conversation_store,
        analysis_service=analysis_service,
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
    background_tasks: BackgroundTasks,
    session: AuthSessionRecord = Depends(get_current_auth_session),
    client: GoogleWorkspaceClient = Depends(get_google_workspace_client),
    cache: GmailMailboxCache = Depends(get_gmail_mailbox_cache),
    conversation_store: ConversationStore = Depends(get_conversation_store),
    analysis_service: ThreadAnalysisService = Depends(get_thread_analysis_service),
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
    background_tasks.add_task(
        analyze_thread_in_background,
        session=session,
        thread_id=thread_id,
        account_email=account_email,
        access_token=access_token,
        client=client,
        cache=cache,
        conversation_store=conversation_store,
        analysis_service=analysis_service,
    )
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
