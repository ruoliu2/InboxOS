from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from app.core.config import Settings
from app.integrations.google_workspace import GoogleAPIError, GoogleWorkspaceClient
from app.schemas.thread import (
    MailboxCountsResponse,
    MailboxKey,
    ThreadHydrateResponse,
    ThreadPlaceholder,
    ThreadSummaryPage,
)
from app.storage.auth_store import (
    AuthSessionRecord,
    AuthStore,
    LinkedAccountRecord,
    ProviderCredentialRecord,
)
from app.storage.gmail_mailbox_store import (
    GmailMailboxStore,
    GmailMailboxSyncStateRecord,
)

DEFAULT_PAGE_SIZE = 20
WATCH_RENEWAL_WINDOW = timedelta(hours=24)


class GmailMailboxService:
    def __init__(
        self,
        client: GoogleWorkspaceClient,
        mailbox_store: GmailMailboxStore,
        auth_store: AuthStore,
        settings: Settings,
    ) -> None:
        self.client = client
        self.mailbox_store = mailbox_store
        self.auth_store = auth_store
        self.settings = settings

    def get_cached_thread_page(
        self,
        session: AuthSessionRecord,
        *,
        mailbox: MailboxKey,
        unread_only: bool,
        query: str | None,
        page_token: str | None,
    ) -> ThreadSummaryPage | None:
        if page_token is not None or query is not None:
            return None
        linked_account_id = session.active_linked_account_id
        if not linked_account_id:
            return None
        return self.mailbox_store.get_thread_page(
            linked_account_id,
            mailbox_key=mailbox.value,
            unread_only=unread_only,
            query=query,
            page_key=page_token,
        )

    def list_thread_page(
        self,
        session: AuthSessionRecord,
        *,
        page_size: int,
        page_token: str | None,
        mailbox: MailboxKey,
        unread_only: bool,
        query: str | None,
    ) -> ThreadSummaryPage:
        context = self._session_context(session)
        return self._list_thread_page_for_context(
            linked_account_id=context.linked_account_id,
            access_token=context.access_token,
            page_size=page_size,
            page_token=page_token,
            mailbox=mailbox,
            unread_only=unread_only,
            query=query,
            source="live",
        )

    def refresh_thread_page_cache(
        self,
        session: AuthSessionRecord,
        *,
        page_size: int = DEFAULT_PAGE_SIZE,
        mailbox: MailboxKey = MailboxKey.INBOX,
        unread_only: bool = False,
        query: str | None = None,
    ) -> ThreadSummaryPage:
        try:
            context = self._session_context(session)
            page = self._list_thread_page_for_context(
                linked_account_id=context.linked_account_id,
                access_token=context.access_token,
                page_size=page_size,
                page_token=None,
                mailbox=mailbox,
                unread_only=unread_only,
                query=query,
                source="live",
            )
            if query is None:
                try:
                    self.refresh_mailbox_counts(session)
                    self.ensure_watch(session)
                    self._touch_linked_account(
                        context.account,
                        page.synced_at or datetime.now(UTC),
                    )
                except (GoogleAPIError, RuntimeError):
                    pass
            return page
        except (GoogleAPIError, RuntimeError):
            return ThreadSummaryPage(
                threads=[],
                next_page_token=None,
                has_more=False,
                total_count=None,
                hydrated_count=0,
                source="cache",
                synced_at=datetime.now(UTC),
            )

    def hydrate_threads(
        self, session: AuthSessionRecord, thread_ids: list[str]
    ) -> ThreadHydrateResponse:
        normalized_ids = [
            thread_id.strip() for thread_id in thread_ids if thread_id.strip()
        ]
        if not normalized_ids:
            return ThreadHydrateResponse()

        context = self._session_context(session)
        cached = self.mailbox_store.get_thread_summaries(
            context.linked_account_id, normalized_ids
        )
        missing_ids = [
            thread_id for thread_id in normalized_ids if thread_id not in cached
        ]
        if missing_ids:
            fetched = self.client.get_gmail_thread_summaries(
                context.access_token,
                missing_ids,
            )
            self.mailbox_store.upsert_thread_summaries(
                context.linked_account_id,
                fetched,
            )
            cached.update({thread.id: thread for thread in fetched})

        ordered = {
            thread_id: cached[thread_id]
            for thread_id in normalized_ids
            if thread_id in cached
        }
        return ThreadHydrateResponse(
            threads=ordered,
            hydrated_count=len(ordered),
            synced_at=datetime.now(UTC),
        )

    def get_cached_mailbox_counts(
        self, session: AuthSessionRecord
    ) -> MailboxCountsResponse | None:
        linked_account_id = session.active_linked_account_id
        if not linked_account_id:
            return None
        return self.mailbox_store.get_mailbox_counts(linked_account_id)

    def refresh_mailbox_counts(
        self, session: AuthSessionRecord
    ) -> MailboxCountsResponse:
        context = self._session_context(session)
        counts = self.client.get_gmail_mailbox_counts(context.access_token)
        self.mailbox_store.upsert_mailbox_counts(
            context.linked_account_id,
            counts,
            synced_at=datetime.now(UTC),
        )
        return counts

    def refresh_mailbox_counts_safe(self, session: AuthSessionRecord) -> None:
        try:
            self.refresh_mailbox_counts(session)
        except (GoogleAPIError, RuntimeError):
            return

    def get_mailbox_counts(self, session: AuthSessionRecord) -> MailboxCountsResponse:
        cached = self.get_cached_mailbox_counts(session)
        if cached is not None:
            return cached
        return self.refresh_mailbox_counts(session)

    def seed_linked_account(self, linked_account_id: str) -> None:
        try:
            context = self._linked_account_context(linked_account_id)
            self._refresh_standard_mailbox_state(context)
        except (GoogleAPIError, RuntimeError):
            return

    def seed_session(self, session: AuthSessionRecord) -> None:
        try:
            self._refresh_standard_mailbox_state(self._session_context(session))
        except (GoogleAPIError, RuntimeError):
            return

    def ensure_watch(self, session: AuthSessionRecord) -> None:
        try:
            self._ensure_watch(self._session_context(session))
        except (GoogleAPIError, RuntimeError):
            return

    def handle_watch_notification(
        self, account_email: str, history_id: str | None
    ) -> None:
        normalized_email = account_email.strip().lower()
        sync_state = self.mailbox_store.get_sync_state_by_account_email(
            normalized_email
        )
        if sync_state is None:
            linked_account = self.auth_store.find_linked_account(
                "google_gmail", normalized_email
            )
            if linked_account is None:
                return
            self.seed_linked_account(linked_account.id)
            return

        context = self._linked_account_context(sync_state.linked_account_id)
        if not sync_state.history_id:
            self._refresh_standard_mailbox_state(context)
            return

        try:
            history = self.client.list_gmail_history(
                context.access_token,
                start_history_id=sync_state.history_id,
            )
        except GoogleAPIError as exc:
            if exc.upstream_status_code == 404:
                self._refresh_standard_mailbox_state(context)
                return
            raise

        deleted_ids = list(history.deleted_thread_ids)
        if deleted_ids:
            self.mailbox_store.delete_thread_summaries(
                context.linked_account_id, deleted_ids
            )

        changed_ids = [
            thread_id
            for thread_id in history.changed_thread_ids
            if thread_id not in set(deleted_ids)
        ]
        if changed_ids:
            refreshed = self.client.get_gmail_thread_summaries(
                context.access_token,
                changed_ids,
            )
            self.mailbox_store.upsert_thread_summaries(
                context.linked_account_id,
                refreshed,
                history_id=history.history_id,
            )

        self.mailbox_store.invalidate_account_pages(context.linked_account_id)
        self._refresh_standard_mailbox_state(context, refresh_only=True)

        now = datetime.now(UTC)
        self.mailbox_store.upsert_sync_state(
            GmailMailboxSyncStateRecord(
                linked_account_id=context.linked_account_id,
                account_email=normalized_email,
                history_id=history_id or history.history_id,
                watch_expiration=sync_state.watch_expiration,
                last_sync_status="ok",
                last_synced_at=now,
                created_at=sync_state.created_at,
                updated_at=now,
            )
        )

    def _refresh_standard_mailbox_state(
        self,
        context: _MailboxContext,
        *,
        refresh_only: bool = False,
    ) -> None:
        page = self._list_thread_page_for_context(
            linked_account_id=context.linked_account_id,
            access_token=context.access_token,
            page_size=DEFAULT_PAGE_SIZE,
            page_token=None,
            mailbox=MailboxKey.INBOX,
            unread_only=False,
            query=None,
            source="cache",
        )
        counts = self.client.get_gmail_mailbox_counts(context.access_token)
        synced_at = page.synced_at or datetime.now(UTC)
        self.mailbox_store.upsert_mailbox_counts(
            context.linked_account_id,
            counts,
            synced_at=synced_at,
        )
        self._ensure_watch(context)
        if not refresh_only:
            self._touch_linked_account(context.account, synced_at)

    def _list_thread_page_for_context(
        self,
        *,
        linked_account_id: str,
        access_token: str,
        page_size: int,
        page_token: str | None,
        mailbox: MailboxKey,
        unread_only: bool,
        query: str | None,
        source: str,
    ) -> ThreadSummaryPage:
        listing = self.client.list_gmail_thread_ids(
            access_token,
            max_results=page_size,
            page_token=page_token,
            mailbox=mailbox,
            unread_only=unread_only,
            query=query,
        )
        cached = self.mailbox_store.get_thread_summaries(
            linked_account_id,
            listing.thread_ids,
        )
        threads = [
            cached.get(thread_id) or ThreadPlaceholder(id=thread_id)
            for thread_id in listing.thread_ids
        ]
        page = ThreadSummaryPage(
            threads=threads,
            next_page_token=listing.next_page_token,
            has_more=listing.next_page_token is not None,
            total_count=listing.total_count,
            hydrated_count=len(cached),
            source=source,
            synced_at=datetime.now(UTC),
        )
        self.mailbox_store.store_thread_page(
            linked_account_id,
            page=page,
            mailbox_key=mailbox.value,
            unread_only=unread_only,
            query=query,
            page_key=page_token,
        )
        return page

    def _ensure_watch(self, context: _MailboxContext | AuthSessionRecord) -> None:
        resolved = (
            context
            if isinstance(context, _MailboxContext)
            else self._session_context(context)
        )
        topic_name = (self.settings.gmail_watch_topic_name or "").strip()
        if not topic_name:
            return
        sync_state = self.mailbox_store.get_sync_state(resolved.linked_account_id)
        now = datetime.now(UTC)
        if (
            sync_state is not None
            and sync_state.watch_expiration is not None
            and sync_state.watch_expiration > now + WATCH_RENEWAL_WINDOW
        ):
            return
        watch = self.client.watch_gmail_mailbox(
            resolved.access_token, topic_name=topic_name
        )
        created_at = sync_state.created_at if sync_state is not None else now
        self.mailbox_store.upsert_sync_state(
            GmailMailboxSyncStateRecord(
                linked_account_id=resolved.linked_account_id,
                account_email=resolved.account.provider_account_id,
                history_id=watch.history_id,
                watch_expiration=watch.expiration,
                last_sync_status="watching",
                last_synced_at=(
                    sync_state.last_synced_at if sync_state is not None else now
                ),
                created_at=created_at,
                updated_at=now,
            )
        )

    def _session_context(self, session: AuthSessionRecord) -> _MailboxContext:
        if not session.active_linked_account_id or not session.access_token:
            raise RuntimeError("An active linked Google account is required.")
        account = self.auth_store.get_linked_account_by_id(
            session.active_linked_account_id
        )
        if account is None:
            raise RuntimeError("Linked account not found.")
        return _MailboxContext(
            linked_account_id=account.id,
            access_token=session.access_token,
            account=account,
        )

    def _linked_account_context(self, linked_account_id: str) -> _MailboxContext:
        account = self.auth_store.get_linked_account_by_id(linked_account_id)
        if account is None:
            raise RuntimeError(f"Linked account {linked_account_id} not found.")
        credential = self.auth_store.get_provider_credential(linked_account_id)
        if credential is None:
            raise RuntimeError(
                f"Provider credentials for {linked_account_id} not found."
            )
        credential = self._refresh_credential_if_needed(credential)
        return _MailboxContext(
            linked_account_id=linked_account_id,
            access_token=credential.access_token,
            account=account,
        )

    def _refresh_credential_if_needed(
        self, credential: ProviderCredentialRecord
    ) -> ProviderCredentialRecord:
        if credential.expires_at is None or credential.expires_at > datetime.now(UTC):
            return credential
        if not credential.refresh_token:
            raise RuntimeError(
                "Google credential expired and no refresh token is available."
            )
        refreshed = self.client.refresh_access_token(credential.refresh_token)
        updated = replace(
            credential,
            access_token=refreshed.access_token,
            refresh_token=refreshed.refresh_token or credential.refresh_token,
            scope=refreshed.scope or credential.scope,
            expires_at=refreshed.expires_at,
            updated_at=datetime.now(UTC),
        )
        self.auth_store.upsert_provider_credential(updated)
        return updated

    def _touch_linked_account(
        self, account: LinkedAccountRecord, synced_at: datetime
    ) -> None:
        self.auth_store.upsert_linked_account(
            replace(
                account,
                last_synced_at=synced_at,
                updated_at=datetime.now(UTC),
            )
        )


class _MailboxContext:
    def __init__(
        self,
        *,
        linked_account_id: str,
        access_token: str,
        account: LinkedAccountRecord,
    ) -> None:
        self.linked_account_id = linked_account_id
        self.access_token = access_token
        self.account = account
