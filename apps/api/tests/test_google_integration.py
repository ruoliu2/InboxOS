import base64
import json
import sqlite3
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.core.config import get_settings
from app.integrations.google_workspace import (
    GmailOutgoingAttachment,
    GmailThreadIdPage,
    GoogleAPIError,
)
from app.routers.gmail import (
    MAX_GMAIL_ATTACHMENT_BYTES,
    MAX_GMAIL_MESSAGE_ATTACHMENTS,
)
from app.schemas.calendar import CalendarEvent
from app.schemas.common import ActionState
from app.schemas.thread import (
    ComposeMode,
    ComposeThreadRequest,
    MailboxCountsResponse,
    SendGmailMessageRequest,
    ThreadDetail,
    ThreadInlineAsset,
    ThreadMessage,
    ThreadSummary,
    ThreadSummaryPage,
)
from app.services.dependencies import (
    get_auth_service,
    get_auth_store,
    get_gmail_mailbox_cache,
    get_gmail_mailbox_service,
    get_gmail_mailbox_store,
    get_google_workspace_client,
)
from app.storage.auth_store import AuthSessionRecord
from app.storage.mailbox_cache import GmailMailboxCache


def build_session(**overrides: object) -> AuthSessionRecord:
    now = datetime.now(UTC)
    values: dict[str, object] = {
        "session_id": "session-1",
        "provider": "google_gmail",
        "account_email": "user@gmail.com",
        "account_name": "Inbox User",
        "account_picture": None,
        "access_token": "access-token",
        "refresh_token": "refresh-token",
        "scope": "email profile",
        "expires_at": now + timedelta(hours=1),
        "session_expires_at": now + timedelta(days=30),
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    return AuthSessionRecord(**values)


def mock_google_login(monkeypatch: pytest.MonkeyPatch) -> None:
    google_client = get_google_workspace_client()

    monkeypatch.setattr(
        google_client,
        "build_authorization_url",
        lambda state: f"https://accounts.google.com/mock?state={state}",
    )
    monkeypatch.setattr(
        google_client,
        "exchange_code_for_tokens",
        lambda code: type(
            "TokenBundle",
            (),
            {
                "access_token": "access-token",
                "refresh_token": "refresh-token",
                "scope": "email profile",
                "expires_at": datetime.now(UTC) + timedelta(hours=1),
            },
        )(),
    )
    monkeypatch.setattr(
        google_client,
        "get_user_profile",
        lambda access_token: type(
            "GoogleUserProfile",
            (),
            {
                "email": "user@gmail.com",
                "name": "Inbox User",
                "picture": None,
            },
        )(),
    )


def encode_gmail_body(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("utf-8").rstrip("=")


def restart_auth_dependencies() -> None:
    get_settings.cache_clear()
    get_auth_service.cache_clear()
    get_auth_store.cache_clear()


def test_google_callback_sets_persistent_session_cookie_and_redirects(
    client,
    monkeypatch,
):
    mock_google_login(monkeypatch)

    start_response = client.get("/auth/google/start?redirect_to=/calendar")
    assert start_response.status_code == 200
    state = start_response.json()["state"]

    callback_response = client.get(
        f"/auth/google/callback?code=test-code&state={state}",
        follow_redirects=False,
    )
    assert callback_response.status_code == 303
    assert callback_response.headers["location"] == "http://localhost:3000/calendar"
    cookie_header = callback_response.headers["set-cookie"]
    assert "inboxos_session=" in cookie_header
    assert f"Max-Age={get_settings().session_ttl_seconds}" in cookie_header
    assert "expires=" in cookie_header.lower()

    session_id = client.cookies.get(get_settings().session_cookie_name)
    assert session_id is not None
    assert get_auth_store().get_session(session_id) is not None


def test_google_callback_uses_none_samesite_for_secure_cookie(client, monkeypatch):
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "true")
    restart_auth_dependencies()
    mock_google_login(monkeypatch)

    start_response = client.get("/auth/google/start?redirect_to=/mail")
    state = start_response.json()["state"]

    callback_response = client.get(
        f"/auth/google/callback?code=test-code&state={state}",
        follow_redirects=False,
    )

    cookie_header = callback_response.headers["set-cookie"]
    assert "SameSite=none" in cookie_header
    assert "Secure" in cookie_header


def test_auth_session_survives_service_restart(client, monkeypatch):
    mock_google_login(monkeypatch)

    start_response = client.get("/auth/google/start?redirect_to=/calendar")
    state = start_response.json()["state"]
    client.get(
        f"/auth/google/callback?code=test-code&state={state}",
        follow_redirects=False,
    )

    restart_auth_dependencies()

    session_response = client.get("/auth/session")
    assert session_response.status_code == 200
    assert session_response.json()["authenticated"] is True
    assert session_response.json()["account_email"] == "user@gmail.com"


def test_google_oauth_state_survives_service_restart(client, monkeypatch):
    mock_google_login(monkeypatch)

    start_response = client.get("/auth/google/start?redirect_to=/calendar")
    state = start_response.json()["state"]

    restart_auth_dependencies()

    callback_response = client.get(
        f"/auth/google/callback?code=test-code&state={state}",
        follow_redirects=False,
    )
    assert callback_response.status_code == 303
    assert callback_response.headers["location"] == "http://localhost:3000/calendar"


def test_auth_session_route_reissues_cookie_and_extends_session_expiry(client):
    auth_store = get_auth_store()
    session = build_session(session_expires_at=datetime.now(UTC) + timedelta(minutes=5))
    auth_store.upsert_session(session)
    client.cookies.set(
        get_settings().session_cookie_name,
        session.session_id,
        domain="testserver.local",
    )

    response = client.get("/auth/session")

    assert response.status_code == 200
    assert response.json()["authenticated"] is True
    assert (
        f"Max-Age={get_settings().session_ttl_seconds}"
        in response.headers["set-cookie"]
    )
    refreshed_session = auth_store.get_session(session.session_id)
    assert refreshed_session is not None
    assert (
        refreshed_session.session_expires_at
        > session.session_expires_at + timedelta(days=20)
    )


def test_expired_app_session_returns_unauthenticated_and_is_deleted(client):
    auth_store = get_auth_store()
    session = build_session(
        session_expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    auth_store.upsert_session(session)
    client.cookies.set(
        get_settings().session_cookie_name,
        session.session_id,
        domain="testserver.local",
    )

    response = client.get("/auth/session")

    assert response.status_code == 200
    assert response.json()["authenticated"] is False
    assert auth_store.get_session(session.session_id) is None


def test_expired_google_access_token_refreshes_session(client, monkeypatch):
    auth_store = get_auth_store()
    session = build_session(
        access_token="stale-access-token",
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    auth_store.upsert_session(session)
    client.cookies.set(
        get_settings().session_cookie_name,
        session.session_id,
        domain="testserver.local",
    )

    google_client = get_google_workspace_client()
    monkeypatch.setattr(
        google_client,
        "refresh_access_token",
        lambda refresh_token: type(
            "TokenBundle",
            (),
            {
                "access_token": "fresh-access-token",
                "refresh_token": "fresh-refresh-token",
                "scope": "email profile",
                "expires_at": datetime.now(UTC) + timedelta(hours=1),
            },
        )(),
    )

    response = client.get("/auth/session")

    assert response.status_code == 200
    assert response.json()["authenticated"] is True
    refreshed_session = auth_store.get_session(session.session_id)
    assert refreshed_session is not None
    assert refreshed_session.access_token == "fresh-access-token"
    assert refreshed_session.refresh_token == "fresh-refresh-token"


def test_missing_refresh_token_deletes_expired_session(client):
    auth_store = get_auth_store()
    session = build_session(
        refresh_token=None,
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    auth_store.upsert_session(session)
    client.cookies.set(
        get_settings().session_cookie_name,
        session.session_id,
        domain="testserver.local",
    )

    response = client.get("/auth/session")

    assert response.status_code == 200
    assert response.json()["authenticated"] is False
    assert auth_store.get_session(session.session_id) is None


def test_refresh_failure_returns_401_and_deletes_session(client, monkeypatch):
    auth_store = get_auth_store()
    session = build_session(expires_at=datetime.now(UTC) - timedelta(minutes=1))
    auth_store.upsert_session(session)
    client.cookies.set(
        get_settings().session_cookie_name,
        session.session_id,
        domain="testserver.local",
    )

    google_client = get_google_workspace_client()
    monkeypatch.setattr(
        google_client,
        "refresh_access_token",
        lambda refresh_token: (_ for _ in ()).throw(RuntimeError("refresh failed")),
    )

    response = client.get("/gmail/threads")

    assert response.status_code == 401
    assert auth_store.get_session(session.session_id) is None


def test_refresh_failure_with_string_google_error_returns_unauthenticated(
    monkeypatch,
):
    auth_store = get_auth_store()
    session = build_session(expires_at=datetime.now(UTC) - timedelta(minutes=1))
    auth_store.upsert_session(session)

    def fake_request(self, method, url, **kwargs):
        return httpx.Response(
            400,
            json={
                "error": "invalid_grant",
                "error_description": "Token has been expired or revoked.",
            },
            request=httpx.Request(method, url),
        )

    monkeypatch.setattr(httpx.Client, "request", fake_request)
    service = get_auth_service()

    assert service.get_session(session.session_id) is None
    assert auth_store.get_session(session.session_id) is None


def test_logout_removes_persisted_session_and_clears_cookie(client):
    auth_store = get_auth_store()
    session = build_session()
    auth_store.upsert_session(session)
    client.cookies.set(
        get_settings().session_cookie_name,
        session.session_id,
        domain="testserver.local",
    )

    response = client.post("/auth/logout")

    assert response.status_code == 204
    assert auth_store.get_session(session.session_id) is None
    assert "expires=" in response.headers["set-cookie"].lower()
    follow_up = client.get("/auth/session")
    assert follow_up.json()["authenticated"] is False


def test_protected_routes_reissue_cookie(client, monkeypatch):
    auth_store = get_auth_store()
    session = build_session(session_expires_at=datetime.now(UTC) + timedelta(minutes=5))
    auth_store.upsert_session(session)
    client.cookies.set(
        get_settings().session_cookie_name,
        session.session_id,
        domain="testserver.local",
    )

    google_client = get_google_workspace_client()
    monkeypatch.setattr(
        google_client,
        "list_gmail_thread_ids",
        lambda access_token, **_: GmailThreadIdPage(
            thread_ids=[],
            next_page_token=None,
            total_count=0,
        ),
    )

    response = client.get("/gmail/threads")

    assert response.status_code == 200
    assert (
        f"Max-Age={get_settings().session_ttl_seconds}"
        in response.headers["set-cookie"]
    )


def test_gmail_routes_require_session(client):
    response = client.get("/gmail/threads")
    assert response.status_code == 401


def test_google_client_normalizes_disabled_gmail_api_errors(monkeypatch):
    google_client = get_google_workspace_client()

    def fake_request(self, method, url, **kwargs):
        return httpx.Response(
            403,
            json={
                "error": {
                    "code": 403,
                    "message": "Gmail API has not been used in project 176323935236 before.",
                    "details": [
                        {
                            "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                            "reason": "SERVICE_DISABLED",
                            "domain": "googleapis.com",
                            "metadata": {
                                "containerInfo": "176323935236",
                                "service": "gmail.googleapis.com",
                                "serviceTitle": "Gmail API",
                                "activationUrl": "https://console.developers.google.com/apis/api/gmail.googleapis.com/overview?project=176323935236",
                            },
                        }
                    ],
                }
            },
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.Client, "request", fake_request)

    with pytest.raises(GoogleAPIError) as exc_info:
        google_client.list_gmail_threads("access-token")

    error = exc_info.value
    assert error.app_status_code == 503
    assert "Gmail API is disabled for Google project 176323935236." in str(error)
    assert (
        "https://console.developers.google.com/apis/api/gmail.googleapis.com/overview?project=176323935236"
        in str(error)
    )


def test_gmail_route_returns_503_for_disabled_google_service(client, monkeypatch):
    auth_store = get_auth_store()
    session = build_session()
    auth_store.upsert_session(session)
    client.cookies.set(
        get_settings().session_cookie_name,
        session.session_id,
        domain="testserver.local",
    )

    google_client = get_google_workspace_client()

    def raise_disabled_error(
        access_token: str,
        *,
        max_results: int = 20,
        page_token: str | None = None,
        mailbox=None,
        unread_only: bool = False,
        query: str | None = None,
    ) -> ThreadSummaryPage:
        raise GoogleAPIError(
            "Gmail API is disabled for Google project 176323935236.",
            upstream_status_code=403,
            app_status_code=503,
        )

    monkeypatch.setattr(google_client, "list_gmail_thread_ids", raise_disabled_error)

    response = client.get("/gmail/threads")

    assert response.status_code == 503
    assert "Gmail API is disabled" in response.json()["detail"]


def test_gmail_and_calendar_routes_use_google_client(client, monkeypatch):
    auth_store = get_auth_store()
    session = build_session()
    auth_store.upsert_session(session)
    client.cookies.set(
        get_settings().session_cookie_name,
        session.session_id,
        domain="testserver.local",
    )

    google_client = get_google_workspace_client()
    mailbox_store = get_gmail_mailbox_store()
    mailbox_store.upsert_thread_summaries(
        get_auth_store().get_session(session.session_id).active_linked_account_id,
        [
            ThreadSummary(
                id="gmail-thread-1",
                subject="Launch checklist",
                snippet="Please confirm the launch checklist.",
                participants=["founder@gmail.com", "user@gmail.com"],
                last_message_at=datetime.now(UTC),
                action_states=[ActionState.TO_REPLY],
            )
        ],
    )
    monkeypatch.setattr(
        google_client,
        "list_gmail_thread_ids",
        lambda access_token, **_: GmailThreadIdPage(
            thread_ids=["gmail-thread-1"],
            next_page_token="next-page",
            total_count=41,
        ),
    )
    monkeypatch.setattr(
        google_client,
        "get_gmail_thread",
        lambda access_token, thread_id: ThreadDetail(
            id=thread_id,
            subject="Launch checklist",
            snippet="Please confirm the launch checklist.",
            participants=["founder@gmail.com", "user@gmail.com"],
            last_message_at=datetime.now(UTC),
            action_states=[ActionState.TO_REPLY],
            messages=[
                ThreadMessage(
                    id="gmail-message-1",
                    sender="founder@gmail.com",
                    sent_at=datetime.now(UTC),
                    body="Please confirm the launch checklist.",
                )
            ],
            analysis=None,
        ),
    )
    monkeypatch.setattr(
        google_client,
        "list_calendar_events",
        lambda access_token, time_min, time_max: [
            CalendarEvent(
                id="event-1",
                title="InboxOS Demo",
                starts_at=datetime.now(UTC),
                ends_at=datetime.now(UTC) + timedelta(hours=1),
                location="Zoom",
                description=None,
                is_all_day=False,
                html_link=None,
            )
        ],
    )

    threads_response = client.get("/gmail/threads")
    assert threads_response.status_code == 200
    assert threads_response.json()["threads"][0]["id"] == "gmail-thread-1"
    assert threads_response.json()["next_page_token"] == "next-page"
    assert threads_response.json()["total_count"] == 41

    thread_response = client.get("/gmail/threads/gmail-thread-1")
    assert thread_response.status_code == 200
    assert thread_response.json()["id"] == "gmail-thread-1"

    calendar_response = client.get("/calendar/events")
    assert calendar_response.status_code == 200
    assert calendar_response.json()[0]["title"] == "InboxOS Demo"


def test_gmail_route_returns_cached_first_page_before_refresh(client, monkeypatch):
    auth_store = get_auth_store()
    session = build_session()
    auth_store.upsert_session(session)
    client.cookies.set(
        get_settings().session_cookie_name,
        session.session_id,
        domain="testserver.local",
    )

    auth_session = get_auth_store().get_session(session.session_id)
    assert auth_session is not None
    mailbox_store = get_gmail_mailbox_store()
    mailbox_store.upsert_thread_summaries(
        auth_session.active_linked_account_id,
        [
            ThreadSummary(
                id="cached-thread-1",
                subject="Cached summary",
                snippet="Cached startup page.",
                participants=["cached@example.com", session.account_email],
                last_message_at=datetime.now(UTC),
                action_states=[ActionState.FYI],
            )
        ],
    )
    mailbox_store.store_thread_page(
        auth_session.active_linked_account_id,
        page=ThreadSummaryPage(
            threads=[
                ThreadSummary(
                    id="cached-thread-1",
                    subject="Cached summary",
                    snippet="Cached startup page.",
                    participants=["cached@example.com", session.account_email],
                    last_message_at=datetime.now(UTC),
                    action_states=[ActionState.FYI],
                )
            ],
            next_page_token="cached-next",
            has_more=True,
            total_count=17,
            source="cache",
        ),
        page_key=None,
    )

    google_client = get_google_workspace_client()

    def fail_live_fetch(
        access_token: str,
        *,
        max_results: int = 20,
        page_token: str | None = None,
        mailbox=None,
        unread_only: bool = False,
        query: str | None = None,
    ) -> ThreadSummaryPage:
        raise RuntimeError("live fetch should not block cached startup")

    monkeypatch.setattr(google_client, "list_gmail_thread_ids", fail_live_fetch)

    response = client.get("/gmail/threads")

    assert response.status_code == 200
    assert response.json()["threads"][0]["id"] == "cached-thread-1"
    assert response.json()["next_page_token"] == "cached-next"
    assert response.json()["total_count"] == 17


def test_gmail_route_returns_cached_empty_first_page_with_total_count(
    client, monkeypatch
):
    auth_store = get_auth_store()
    session = build_session()
    auth_store.upsert_session(session)
    client.cookies.set(
        get_settings().session_cookie_name,
        session.session_id,
        domain="testserver.local",
    )

    auth_session = get_auth_store().get_session(session.session_id)
    assert auth_session is not None
    mailbox_store = get_gmail_mailbox_store()
    mailbox_store.store_thread_page(
        auth_session.active_linked_account_id,
        mailbox_key="inbox",
        unread_only=False,
        page=ThreadSummaryPage(
            threads=[],
            next_page_token=None,
            has_more=False,
            total_count=0,
            source="cache",
        ),
        page_key=None,
    )

    google_client = get_google_workspace_client()

    def fail_live_fetch(
        access_token: str,
        *,
        max_results: int = 20,
        page_token: str | None = None,
        mailbox=None,
        unread_only: bool = False,
        query: str | None = None,
    ) -> ThreadSummaryPage:
        raise RuntimeError("live fetch should not block cached startup")

    monkeypatch.setattr(google_client, "list_gmail_thread_ids", fail_live_fetch)

    response = client.get("/gmail/threads")

    assert response.status_code == 200
    assert response.json()["threads"] == []
    assert response.json()["total_count"] == 0


def test_gmail_mailbox_counts_route_returns_label_totals(client, monkeypatch):
    auth_store = get_auth_store()
    session = build_session()
    auth_store.upsert_session(session)
    client.cookies.set(get_settings().session_cookie_name, session.session_id)

    google_client = get_google_workspace_client()
    monkeypatch.setattr(
        google_client,
        "get_gmail_mailbox_counts",
        lambda access_token: MailboxCountsResponse(
            inbox=1524,
            sent=201,
            archive=None,
            trash=8,
            junk=2,
        ),
    )

    response = client.get("/gmail/mailbox-counts")

    assert response.status_code == 200
    assert response.json() == {
        "inbox": 1524,
        "sent": 201,
        "archive": None,
        "trash": 8,
        "junk": 2,
    }


def test_gmail_route_forwards_pagination_options(client, monkeypatch):
    auth_store = get_auth_store()
    session = build_session()
    auth_store.upsert_session(session)
    client.cookies.set(
        get_settings().session_cookie_name,
        session.session_id,
        domain="testserver.local",
    )

    google_client = get_google_workspace_client()
    captured: dict[str, object] = {}

    def list_thread_ids(
        access_token: str,
        *,
        max_results: int = 20,
        page_token: str | None = None,
        mailbox=None,
        unread_only: bool = False,
        query: str | None = None,
    ) -> GmailThreadIdPage:
        captured["max_results"] = max_results
        captured["page_token"] = page_token
        captured["mailbox"] = mailbox.value if mailbox is not None else None
        captured["unread_only"] = unread_only
        captured["query"] = query
        return GmailThreadIdPage(
            thread_ids=[],
            next_page_token=None,
            total_count=0,
        )

    monkeypatch.setattr(google_client, "list_gmail_thread_ids", list_thread_ids)

    response = client.get(
        "/gmail/threads?page_size=10&page_token=cursor-2&q=from:founder"
    )

    assert response.status_code == 200
    assert captured == {
        "max_results": 10,
        "page_token": "cursor-2",
        "mailbox": "inbox",
        "unread_only": False,
        "query": "from:founder",
    }


def test_gmail_route_forwards_mailbox_and_unread_filters(client, monkeypatch):
    auth_store = get_auth_store()
    session = build_session()
    auth_store.upsert_session(session)
    client.cookies.set(
        get_settings().session_cookie_name,
        session.session_id,
        domain="testserver.local",
    )

    google_client = get_google_workspace_client()
    captured: dict[str, object] = {}

    def list_thread_ids(access_token: str, **kwargs) -> GmailThreadIdPage:
        captured.update(kwargs)
        return GmailThreadIdPage(thread_ids=[], next_page_token=None, total_count=0)

    monkeypatch.setattr(google_client, "list_gmail_thread_ids", list_thread_ids)

    response = client.get(
        "/gmail/threads?mailbox=archive&unread_only=true&q=label:team"
    )

    assert response.status_code == 200
    assert captured["mailbox"].value == "archive"
    assert captured["unread_only"] is True
    assert captured["query"] == "label:team"


def test_gmail_threads_route_returns_placeholders_before_hydration(client, monkeypatch):
    auth_store = get_auth_store()
    session = build_session()
    auth_store.upsert_session(session)
    client.cookies.set(
        get_settings().session_cookie_name,
        session.session_id,
        domain="testserver.local",
    )

    google_client = get_google_workspace_client()
    monkeypatch.setattr(
        google_client,
        "list_gmail_thread_ids",
        lambda access_token, **_: GmailThreadIdPage(
            thread_ids=["thread-a", "thread-b"],
            next_page_token="cursor-2",
            total_count=12,
        ),
    )

    response = client.get("/gmail/threads")

    assert response.status_code == 200
    assert response.json()["threads"] == [
        {"state": "placeholder", "id": "thread-a"},
        {"state": "placeholder", "id": "thread-b"},
    ]
    assert response.json()["hydrated_count"] == 0


def test_gmail_hydrate_route_fetches_requested_ids_and_preserves_order(
    client, monkeypatch
):
    auth_store = get_auth_store()
    session = build_session()
    auth_store.upsert_session(session)
    client.cookies.set(
        get_settings().session_cookie_name,
        session.session_id,
        domain="testserver.local",
    )

    google_client = get_google_workspace_client()
    captured: list[str] = []

    def fetch_summaries(
        access_token: str, thread_ids: list[str]
    ) -> list[ThreadSummary]:
        captured.extend(thread_ids)
        now = datetime.now(UTC)
        return [
            ThreadSummary(
                id=thread_id,
                subject=f"Subject {thread_id}",
                snippet=f"Snippet {thread_id}",
                participants=["founder@gmail.com", "user@gmail.com"],
                last_message_at=now,
                action_states=[ActionState.FYI],
            )
            for thread_id in thread_ids
        ]

    monkeypatch.setattr(google_client, "get_gmail_thread_summaries", fetch_summaries)

    response = client.post(
        "/gmail/threads/hydrate",
        json={"thread_ids": ["thread-b", "thread-a"]},
    )

    assert response.status_code == 200
    assert captured == ["thread-b", "thread-a"]
    assert list(response.json()["threads"].keys()) == ["thread-b", "thread-a"]
    assert response.json()["threads"]["thread-b"]["state"] == "ready"


def test_gmail_mailbox_counts_route_returns_cached_counts_before_refresh(
    client, monkeypatch
):
    auth_store = get_auth_store()
    session = build_session()
    auth_store.upsert_session(session)
    client.cookies.set(
        get_settings().session_cookie_name,
        session.session_id,
        domain="testserver.local",
    )
    stored_session = auth_store.get_session(session.session_id)
    assert stored_session is not None

    get_gmail_mailbox_store().upsert_mailbox_counts(
        stored_session.active_linked_account_id,
        MailboxCountsResponse(
            inbox=88,
            sent=21,
            archive=None,
            trash=3,
            junk=1,
        ),
        synced_at=datetime.now(UTC),
    )

    google_client = get_google_workspace_client()
    monkeypatch.setattr(
        google_client,
        "get_gmail_mailbox_counts",
        lambda access_token: (_ for _ in ()).throw(
            RuntimeError("refresh should not block cached counts")
        ),
    )

    response = client.get("/gmail/mailbox-counts")

    assert response.status_code == 200
    assert response.json()["inbox"] == 88
    assert response.json()["trash"] == 3


def test_gmail_watch_route_forwards_notification_payload(client, monkeypatch):
    service = get_gmail_mailbox_service()
    captured: dict[str, str | None] = {}

    monkeypatch.setattr(
        service,
        "handle_watch_notification",
        lambda account_email, history_id: captured.update(
            {"account_email": account_email, "history_id": history_id}
        ),
    )

    encoded = base64.urlsafe_b64encode(
        json.dumps({"emailAddress": "user@gmail.com", "historyId": "123456789"}).encode(
            "utf-8"
        )
    ).decode("utf-8")

    response = client.post(
        "/gmail/internal/watch",
        json={"message": {"data": encoded}},
    )

    assert response.status_code == 200
    assert captured == {
        "account_email": "user@gmail.com",
        "history_id": "123456789",
    }


def test_compose_route_updates_detail_cache_and_response(client, monkeypatch):
    auth_store = get_auth_store()
    session = build_session()
    auth_store.upsert_session(session)
    client.cookies.set(
        get_settings().session_cookie_name,
        session.session_id,
        domain="testserver.local",
    )

    google_client = get_google_workspace_client()
    thread = ThreadDetail(
        id="gmail-thread-3",
        subject="Reply trail",
        snippet="Latest reply",
        participants=["founder@gmail.com", "user@gmail.com"],
        last_message_at=datetime.now(UTC),
        action_states=[ActionState.FYI],
        messages=[
            ThreadMessage(
                id="gmail-message-3",
                sender="user@gmail.com",
                sent_at=datetime.now(UTC),
                body="Latest reply",
            )
        ],
        analysis=None,
    )
    monkeypatch.setattr(
        google_client,
        "compose_gmail_thread",
        lambda access_token, **_: type(
            "ComposeResult",
            (),
            {
                "thread": thread,
                "sent_message": thread.messages[-1],
            },
        )(),
    )

    response = client.post(
        "/gmail/threads/gmail-thread-3/compose",
        json={"mode": "reply_all", "body": "Looping everybody in."},
    )

    assert response.status_code == 200
    assert response.json()["mode"] == "reply_all"
    cached_thread = get_gmail_mailbox_cache().get_thread_detail(
        session.account_email,
        "gmail-thread-3",
    )
    assert cached_thread is not None
    assert cached_thread.subject == "Reply trail"


def test_reply_route_updates_detail_cache_and_response(client, monkeypatch):
    auth_store = get_auth_store()
    session = build_session()
    auth_store.upsert_session(session)
    client.cookies.set(
        get_settings().session_cookie_name,
        session.session_id,
        domain="testserver.local",
    )

    google_client = get_google_workspace_client()
    captured: dict[str, object] = {}
    thread = ThreadDetail(
        id="gmail-thread-3",
        subject="Reply trail",
        snippet="Latest reply",
        participants=["founder@gmail.com", "user@gmail.com"],
        last_message_at=datetime.now(UTC),
        action_states=[ActionState.FYI],
        messages=[
            ThreadMessage(
                id="gmail-message-3",
                sender="user@gmail.com",
                sent_at=datetime.now(UTC),
                body="Latest reply",
            )
        ],
        analysis=None,
    )

    def compose_thread(access_token, **kwargs):
        captured["payload"] = kwargs["payload"]
        return type(
            "ComposeResult",
            (),
            {
                "thread": thread,
                "sent_message": thread.messages[-1],
            },
        )()

    monkeypatch.setattr(google_client, "compose_gmail_thread", compose_thread)

    response = client.post(
        "/gmail/threads/gmail-thread-3/reply",
        json={"body": "Sending from the dedicated reply route.", "mute_thread": False},
    )

    assert response.status_code == 200
    assert captured["payload"].mode == ComposeMode.REPLY
    assert captured["payload"].body == "Sending from the dedicated reply route."
    cached_thread = get_gmail_mailbox_cache().get_thread_detail(
        session.account_email,
        "gmail-thread-3",
    )
    assert cached_thread is not None
    assert cached_thread.subject == "Reply trail"


def test_send_message_route_accepts_multipart_and_updates_cache(client, monkeypatch):
    auth_store = get_auth_store()
    session = build_session()
    auth_store.upsert_session(session)
    client.cookies.set(
        get_settings().session_cookie_name,
        session.session_id,
        domain="testserver.local",
    )

    google_client = get_google_workspace_client()
    captured: dict[str, object] = {}
    thread = ThreadDetail(
        id="gmail-thread-new",
        subject="Fresh hello",
        snippet="Nice to meet you",
        participants=["friend@example.com", "user@gmail.com"],
        last_message_at=datetime.now(UTC),
        action_states=[ActionState.FYI],
        messages=[
            ThreadMessage(
                id="gmail-message-new",
                sender="user@gmail.com",
                sent_at=datetime.now(UTC),
                body="Nice to meet you",
            )
        ],
        analysis=None,
    )

    def send_message(access_token, **kwargs):
        captured["payload"] = kwargs["payload"]
        captured["attachments"] = kwargs["attachments"]
        return type(
            "ComposeResult",
            (),
            {
                "thread": thread,
                "sent_message": thread.messages[-1],
            },
        )()

    monkeypatch.setattr(google_client, "send_gmail_message", send_message)

    response = client.post(
        "/gmail/messages/send",
        data={
            "to": "friend@example.com",
            "subject": "Fresh hello",
            "body": "Nice to meet you",
        },
        files=[
            (
                "attachments",
                ("hello.png", b"png-bytes", "image/png"),
            )
        ],
    )

    assert response.status_code == 200
    assert captured["payload"] == SendGmailMessageRequest(
        to=["friend@example.com"],
        subject="Fresh hello",
        body="Nice to meet you",
    )
    assert len(captured["attachments"]) == 1
    assert captured["attachments"][0].filename == "hello.png"
    assert captured["attachments"][0].content_type == "image/png"
    assert captured["attachments"][0].data == b"png-bytes"
    cached_thread = get_gmail_mailbox_cache().get_thread_detail(
        session.account_email,
        "gmail-thread-new",
    )
    assert cached_thread is not None
    assert cached_thread.subject == "Fresh hello"


def test_send_message_route_normalizes_attachment_media_type(client, monkeypatch):
    auth_store = get_auth_store()
    session = build_session()
    auth_store.upsert_session(session)
    client.cookies.set(
        get_settings().session_cookie_name,
        session.session_id,
        domain="testserver.local",
    )

    google_client = get_google_workspace_client()
    captured: dict[str, object] = {}
    thread = ThreadDetail(
        id="gmail-thread-new",
        subject="Fresh hello",
        snippet="Nice to meet you",
        participants=["friend@example.com", "user@gmail.com"],
        last_message_at=datetime.now(UTC),
        action_states=[ActionState.FYI],
        messages=[
            ThreadMessage(
                id="gmail-message-new",
                sender="user@gmail.com",
                sent_at=datetime.now(UTC),
                body="Nice to meet you",
            )
        ],
        analysis=None,
    )

    def send_message(access_token, **kwargs):
        captured["attachments"] = kwargs["attachments"]
        return type(
            "ComposeResult",
            (),
            {
                "thread": thread,
                "sent_message": thread.messages[-1],
            },
        )()

    monkeypatch.setattr(google_client, "send_gmail_message", send_message)

    response = client.post(
        "/gmail/messages/send",
        data={
            "to": "friend@example.com",
            "subject": "Fresh hello",
        },
        files=[
            (
                "attachments",
                ("hello.png", b"png-bytes", "image/png; charset=binary"),
            )
        ],
    )

    assert response.status_code == 200
    assert len(captured["attachments"]) == 1
    assert captured["attachments"][0].content_type == "image/png"


def test_send_message_route_rejects_oversized_attachments(client, monkeypatch):
    auth_store = get_auth_store()
    session = build_session()
    auth_store.upsert_session(session)
    client.cookies.set(
        get_settings().session_cookie_name,
        session.session_id,
        domain="testserver.local",
    )

    google_client = get_google_workspace_client()
    monkeypatch.setattr(
        google_client,
        "send_gmail_message",
        lambda access_token, **kwargs: pytest.fail("should not send"),
    )

    response = client.post(
        "/gmail/messages/send",
        data={
            "to": "friend@example.com",
            "subject": "Fresh hello",
        },
        files=[
            (
                "attachments",
                (
                    "too-large.png",
                    b"x" * (MAX_GMAIL_ATTACHMENT_BYTES + 1),
                    "image/png",
                ),
            )
        ],
    )

    assert response.status_code == 413
    assert "10 MiB attachment limit" in response.json()["detail"]


def test_send_message_route_rejects_too_many_attachments(client, monkeypatch):
    auth_store = get_auth_store()
    session = build_session()
    auth_store.upsert_session(session)
    client.cookies.set(
        get_settings().session_cookie_name,
        session.session_id,
        domain="testserver.local",
    )

    google_client = get_google_workspace_client()
    monkeypatch.setattr(
        google_client,
        "send_gmail_message",
        lambda access_token, **kwargs: pytest.fail("should not send"),
    )

    response = client.post(
        "/gmail/messages/send",
        data={
            "to": "friend@example.com",
            "subject": "Fresh hello",
        },
        files=[
            ("attachments", (f"hello-{index}.png", b"x", "image/png"))
            for index in range(MAX_GMAIL_MESSAGE_ATTACHMENTS + 1)
        ],
    )

    assert response.status_code == 413
    assert str(MAX_GMAIL_MESSAGE_ATTACHMENTS) in response.json()["detail"]


def test_send_message_route_rejects_excess_total_attachment_size(
    client,
    monkeypatch,
):
    auth_store = get_auth_store()
    session = build_session()
    auth_store.upsert_session(session)
    client.cookies.set(
        get_settings().session_cookie_name,
        session.session_id,
        domain="testserver.local",
    )

    google_client = get_google_workspace_client()
    monkeypatch.setattr(
        google_client,
        "send_gmail_message",
        lambda access_token, **kwargs: pytest.fail("should not send"),
    )

    chunk = 7 * 1024 * 1024
    response = client.post(
        "/gmail/messages/send",
        data={
            "to": "friend@example.com",
            "subject": "Fresh hello",
        },
        files=[
            ("attachments", ("hello-1.png", b"x" * chunk, "image/png")),
            ("attachments", ("hello-2.png", b"x" * chunk, "image/png")),
            ("attachments", ("hello-3.png", b"x" * chunk, "image/png")),
        ],
    )

    assert response.status_code == 413
    assert "20 MiB total size limit" in response.json()["detail"]


def test_send_message_route_rejects_cross_site_write_when_secure_cookie_enabled(
    client,
    monkeypatch,
):
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "true")
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")
    monkeypatch.setenv("WEB_BASE_URL", "https://app.example.com")
    restart_auth_dependencies()
    try:
        auth_store = get_auth_store()
        session = build_session()
        auth_store.upsert_session(session)
        client.cookies.set(
            get_settings().session_cookie_name,
            session.session_id,
            domain="testserver.local",
        )

        google_client = get_google_workspace_client()
        monkeypatch.setattr(
            google_client,
            "send_gmail_message",
            lambda access_token, **kwargs: pytest.fail("should not send"),
        )

        response = client.post(
            "/gmail/messages/send",
            headers={"origin": "https://evil.example.com"},
            data={
                "to": "friend@example.com",
                "subject": "Fresh hello",
            },
        )

        assert response.status_code == 403
        assert "Cross-site write request rejected." in response.json()["detail"]
    finally:
        monkeypatch.delenv("SESSION_COOKIE_SECURE", raising=False)
        monkeypatch.delenv("CORS_ORIGINS", raising=False)
        monkeypatch.delenv("WEB_BASE_URL", raising=False)
        restart_auth_dependencies()


def test_thread_action_route_invalidates_cached_pages(client, monkeypatch):
    auth_store = get_auth_store()
    session = build_session()
    auth_store.upsert_session(session)
    client.cookies.set(
        get_settings().session_cookie_name,
        session.session_id,
        domain="testserver.local",
    )

    cache = get_gmail_mailbox_cache()
    cache.store_thread_page(
        session.account_email,
        mailbox_key="inbox",
        unread_only=False,
        page=ThreadSummaryPage(
            threads=[
                ThreadSummary(
                    id="gmail-thread-4",
                    subject="Cached page",
                    snippet="Cached snippet",
                    participants=["cached@example.com", session.account_email],
                    last_message_at=datetime.now(UTC),
                    action_states=[ActionState.FYI],
                )
            ],
            next_page_token=None,
            has_more=False,
        ),
    )

    google_client = get_google_workspace_client()
    monkeypatch.setattr(
        google_client,
        "apply_gmail_thread_action",
        lambda access_token, **_: type(
            "ActionResult",
            (),
            {
                "thread_id": "gmail-thread-4",
                "thread": None,
                "deleted": True,
            },
        )(),
    )

    response = client.post(
        "/gmail/threads/gmail-thread-4/action",
        json={"action": "delete"},
    )

    assert response.status_code == 200
    assert (
        cache.get_thread_page(
            session.account_email,
            mailbox_key="inbox",
            unread_only=False,
            page_key=None,
        )
        is None
    )


def test_calendar_mutation_routes_use_google_client(client, monkeypatch):
    auth_store = get_auth_store()
    session = build_session()
    auth_store.upsert_session(session)
    client.cookies.set(
        get_settings().session_cookie_name,
        session.session_id,
        domain="testserver.local",
    )

    google_client = get_google_workspace_client()
    monkeypatch.setattr(
        google_client,
        "create_calendar_event",
        lambda access_token, payload: CalendarEvent(
            id="event-created",
            title=payload.title,
            starts_at=payload.starts_at,
            ends_at=payload.ends_at,
            location=payload.location,
            description=payload.description,
            is_all_day=payload.is_all_day,
            html_link=None,
            can_delete=True,
        ),
    )
    deleted: dict[str, str] = {}
    monkeypatch.setattr(
        google_client,
        "delete_calendar_event",
        lambda access_token, event_id: deleted.setdefault("event_id", event_id),
    )

    create_response = client.post(
        "/calendar/events",
        json={
            "title": "Founder sync",
            "starts_at": datetime.now(UTC).isoformat(),
            "ends_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            "is_all_day": False,
        },
    )

    assert create_response.status_code == 200
    assert create_response.json()["id"] == "event-created"

    delete_response = client.delete("/calendar/events/event-created")
    assert delete_response.status_code == 204
    assert deleted["event_id"] == "event-created"


def test_gmail_reply_includes_from_header(monkeypatch):
    google_client = get_google_workspace_client()
    sent_payload: dict[str, object] = {}

    monkeypatch.setattr(
        google_client,
        "_get_gmail_thread_payload",
        lambda access_token, thread_id: {
            "messages": [
                {
                    "id": "message-1",
                    "payload": {
                        "headers": [
                            {"name": "From", "value": "Founder <founder@example.com>"},
                            {"name": "Subject", "value": "Launch checklist"},
                            {"name": "Message-ID", "value": "<message-1@example.com>"},
                        ]
                    },
                }
            ]
        },
    )

    def capture_request(method: str, url: str, **kwargs):
        sent_payload["method"] = method
        sent_payload["url"] = url
        sent_payload["json"] = kwargs["json"]
        return {}

    monkeypatch.setattr(google_client, "_request", capture_request)
    monkeypatch.setattr(
        google_client,
        "get_gmail_thread",
        lambda access_token, thread_id: ThreadDetail(
            id=thread_id,
            subject="Launch checklist",
            snippet="Reply sent",
            participants=["founder@example.com", "user@gmail.com"],
            last_message_at=datetime.now(UTC),
            action_states=[ActionState.FYI],
            messages=[
                ThreadMessage(
                    id="message-sent",
                    sender="user@gmail.com",
                    sent_at=datetime.now(UTC),
                    body="Confirmed.",
                )
            ],
            analysis=None,
        ),
    )

    google_client.send_gmail_reply(
        "access-token",
        account_email="user@gmail.com",
        thread_id="thread-1",
        body="Confirmed.",
    )

    assert sent_payload["method"] == "POST"
    raw = sent_payload["json"]["raw"]
    padded = raw + "=" * (-len(raw) % 4)
    mime_message = base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8")
    assert "From: user@gmail.com" in mime_message
    assert "To: founder@example.com" in mime_message


def test_gmail_send_message_includes_subject_and_image_attachment(monkeypatch):
    google_client = get_google_workspace_client()
    sent_payload: dict[str, object] = {}
    sent_thread = ThreadDetail(
        id="thread-new",
        subject="Fresh hello",
        snippet="Nice to meet you",
        participants=["friend@example.com", "user@gmail.com"],
        last_message_at=datetime.now(UTC),
        action_states=[ActionState.FYI],
        messages=[
            ThreadMessage(
                id="message-sent",
                sender="user@gmail.com",
                sent_at=datetime.now(UTC),
                body="Nice to meet you",
            )
        ],
        analysis=None,
    )

    def capture_request(method: str, url: str, **kwargs):
        sent_payload["method"] = method
        sent_payload["url"] = url
        sent_payload["json"] = kwargs["json"]
        return {"id": "gmail-api-message-id", "threadId": "thread-new"}

    monkeypatch.setattr(google_client, "_request", capture_request)
    monkeypatch.setattr(
        google_client,
        "get_gmail_thread",
        lambda access_token, thread_id: sent_thread,
    )

    result = google_client.send_gmail_message(
        "access-token",
        account_email="user@gmail.com",
        payload=SendGmailMessageRequest(
            to=["friend@example.com"],
            subject="Fresh hello",
            body="Nice to meet you",
        ),
        attachments=[
            GmailOutgoingAttachment(
                filename="hello.png",
                content_type="image/png",
                data=b"\x89PNG\r\n",
            )
        ],
    )

    assert result.thread == sent_thread
    assert result.sent_message == sent_thread.messages[-1]
    assert sent_payload["method"] == "POST"
    raw = sent_payload["json"]["raw"]
    padded = raw + "=" * (-len(raw) % 4)
    mime_message = base64.urlsafe_b64decode(padded.encode("utf-8")).decode(
        "utf-8",
        errors="replace",
    )
    assert "From: user@gmail.com" in mime_message
    assert "To: friend@example.com" in mime_message
    assert "Subject: Fresh hello" in mime_message
    assert "Content-Type: multipart/mixed;" in mime_message
    assert "Content-Type: image/png" in mime_message
    assert 'filename="hello.png"' in mime_message


def test_gmail_send_message_normalizes_attachment_media_type(monkeypatch):
    google_client = get_google_workspace_client()
    sent_payload: dict[str, object] = {}
    sent_thread = ThreadDetail(
        id="thread-new",
        subject="Fresh hello",
        snippet="Nice to meet you",
        participants=["friend@example.com", "user@gmail.com"],
        last_message_at=datetime.now(UTC),
        action_states=[ActionState.FYI],
        messages=[
            ThreadMessage(
                id="message-sent",
                sender="user@gmail.com",
                sent_at=datetime.now(UTC),
                body="Nice to meet you",
            )
        ],
        analysis=None,
    )

    def capture_request(method: str, url: str, **kwargs):
        sent_payload["json"] = kwargs["json"]
        return {"id": "gmail-api-message-id", "threadId": "thread-new"}

    monkeypatch.setattr(google_client, "_request", capture_request)
    monkeypatch.setattr(
        google_client,
        "get_gmail_thread",
        lambda access_token, thread_id: sent_thread,
    )

    google_client.send_gmail_message(
        "access-token",
        account_email="user@gmail.com",
        payload=SendGmailMessageRequest(
            to=["friend@example.com"],
            subject="Fresh hello",
            body="Nice to meet you",
        ),
        attachments=[
            GmailOutgoingAttachment(
                filename="hello.png",
                content_type="image/png; charset=binary",
                data=b"\x89PNG\r\n",
            )
        ],
    )

    raw = sent_payload["json"]["raw"]
    padded = raw + "=" * (-len(raw) % 4)
    mime_message = base64.urlsafe_b64decode(padded.encode("utf-8")).decode(
        "utf-8",
        errors="replace",
    )
    assert "Content-Type: image/png" in mime_message
    assert "charset=binary" not in mime_message


def test_google_client_converts_html_breaks_to_newlines():
    google_client = get_google_workspace_client()
    html = "<div>Line one<br>Line two<br/>Line three<br />Line four</div>"
    encoded_html = base64.urlsafe_b64encode(html.encode("utf-8")).decode("utf-8")

    body = google_client._extract_message_body(
        {
            "mimeType": "multipart/alternative",
            "parts": [
                {
                    "mimeType": "text/html",
                    "body": {"data": encoded_html},
                }
            ],
        }
    )

    assert body == "Line one\nLine two\nLine three\nLine four"


def test_google_client_prefers_plain_text_body_and_preserves_html():
    google_client = get_google_workspace_client()
    plain = "Plain launch update"
    html = "<div><strong>Styled</strong> launch update</div>"

    message = google_client._parse_message(
        "access-token",
        {
            "id": "message-plain-html",
            "internalDate": str(int(datetime.now(UTC).timestamp() * 1000)),
            "payload": {
                "headers": [
                    {"name": "From", "value": "Founder <founder@example.com>"},
                ],
                "mimeType": "multipart/alternative",
                "parts": [
                    {
                        "mimeType": "text/plain",
                        "body": {
                            "data": base64.urlsafe_b64encode(
                                plain.encode("utf-8")
                            ).decode("utf-8")
                        },
                    },
                    {
                        "mimeType": "text/html",
                        "body": {
                            "data": base64.urlsafe_b64encode(
                                html.encode("utf-8")
                            ).decode("utf-8")
                        },
                    },
                ],
            },
        },
    )

    assert message.body == plain
    assert message.body_html == html
    assert message.inline_assets == []


def test_google_client_derives_plain_body_from_html_only_message():
    google_client = get_google_workspace_client()
    html = "<div>Hello<br><strong>team</strong></div>"

    message = google_client._parse_message(
        "access-token",
        {
            "id": "message-html-only",
            "internalDate": str(int(datetime.now(UTC).timestamp() * 1000)),
            "payload": {
                "headers": [
                    {"name": "From", "value": "Founder <founder@example.com>"},
                ],
                "mimeType": "multipart/alternative",
                "parts": [
                    {
                        "mimeType": "text/html",
                        "body": {
                            "data": base64.urlsafe_b64encode(
                                html.encode("utf-8")
                            ).decode("utf-8")
                        },
                    }
                ],
            },
        },
    )

    assert message.body == "Hello\nteam"
    assert message.body_html == html
    assert message.inline_assets == []


def test_google_client_collects_cid_inline_assets_from_attachment_parts(monkeypatch):
    google_client = get_google_workspace_client()
    html = '<div><img src="cid:hero.png" alt="Hero"></div>'
    png_bytes = b"\x89PNG\r\n\x1a\n"
    encoded_attachment = base64.urlsafe_b64encode(png_bytes).decode("utf-8")

    def fake_request(method: str, url: str, **kwargs):
        if url.endswith("/messages/message-inline/attachments/att-inline"):
            return {"data": encoded_attachment}
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr(google_client, "_request", fake_request)

    message = google_client._parse_message(
        "access-token",
        {
            "id": "message-inline",
            "internalDate": str(int(datetime.now(UTC).timestamp() * 1000)),
            "payload": {
                "headers": [
                    {"name": "From", "value": "Founder <founder@example.com>"},
                ],
                "mimeType": "multipart/related",
                "parts": [
                    {
                        "mimeType": "text/html",
                        "body": {
                            "data": base64.urlsafe_b64encode(
                                html.encode("utf-8")
                            ).decode("utf-8")
                        },
                    },
                    {
                        "mimeType": "image/png",
                        "headers": [
                            {"name": "Content-ID", "value": "<hero.png>"},
                        ],
                        "body": {
                            "attachmentId": "att-inline",
                        },
                    },
                ],
            },
        },
    )

    assert message.body_html == html
    assert message.inline_assets == [
        ThreadInlineAsset(
            content_id="hero.png",
            mime_type="image/png",
            data_url=(
                "data:image/png;base64,"
                f"{base64.b64encode(png_bytes).decode('ascii')}"
            ),
        )
    ]


def test_google_client_skips_inline_assets_when_attachment_fetch_fails(monkeypatch):
    google_client = get_google_workspace_client()
    html = '<div><img src="cid:hero.png" alt="Hero"></div>'

    def fake_request(method: str, url: str, **kwargs):
        if url.endswith("/messages/message-inline/attachments/att-inline"):
            raise GoogleAPIError(
                "attachment missing",
                upstream_status_code=404,
                app_status_code=404,
            )
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr(google_client, "_request", fake_request)

    message = google_client._parse_message(
        "access-token",
        {
            "id": "message-inline",
            "internalDate": str(int(datetime.now(UTC).timestamp() * 1000)),
            "payload": {
                "headers": [
                    {"name": "From", "value": "Founder <founder@example.com>"},
                ],
                "mimeType": "multipart/related",
                "parts": [
                    {
                        "mimeType": "text/html",
                        "body": {
                            "data": base64.urlsafe_b64encode(
                                html.encode("utf-8")
                            ).decode("utf-8")
                        },
                    },
                    {
                        "mimeType": "image/png",
                        "headers": [
                            {"name": "Content-ID", "value": "<hero.png>"},
                        ],
                        "body": {
                            "attachmentId": "att-inline",
                        },
                    },
                ],
            },
        },
    )

    assert message.body_html == html
    assert message.body == ""
    assert message.inline_assets == []


def test_google_client_iterates_deeply_nested_parts_without_recursion():
    google_client = get_google_workspace_client()
    deepest_html = "<div>nested</div>"
    payload: dict[str, object] = {
        "mimeType": "multipart/related",
        "parts": [],
    }
    current = payload
    for _ in range(1500):
        child: dict[str, object] = {
            "mimeType": "multipart/related",
            "parts": [],
        }
        current["parts"] = [child]
        current = child
    current["parts"] = [
        {
            "mimeType": "text/html",
            "body": {
                "data": base64.urlsafe_b64encode(deepest_html.encode("utf-8")).decode(
                    "utf-8"
                )
            },
        }
    ]

    assert google_client._find_body_part(payload, "text/html") == deepest_html


def test_calendar_route_preserves_explicit_time_window(client, monkeypatch):
    auth_store = get_auth_store()
    session = build_session()
    auth_store.upsert_session(session)
    client.cookies.set(
        get_settings().session_cookie_name,
        session.session_id,
        domain="testserver.local",
    )

    google_client = get_google_workspace_client()
    captured: dict[str, datetime] = {}

    def list_events(access_token: str, time_min: datetime, time_max: datetime):
        captured["time_min"] = time_min
        captured["time_max"] = time_max
        return []

    monkeypatch.setattr(google_client, "list_calendar_events", list_events)

    response = client.get(
        "/calendar/events?time_min=2026-03-01T10:00:00Z&time_max=2026-03-05T18:30:00Z"
    )

    assert response.status_code == 200
    assert captured == {
        "time_min": datetime(2026, 3, 1, 10, 0, tzinfo=UTC),
        "time_max": datetime(2026, 3, 5, 18, 30, tzinfo=UTC),
    }


def test_gmail_mailbox_cache_connect_closes_connection():
    cache = get_gmail_mailbox_cache()

    with cache._connect() as connection:
        connection.execute("SELECT 1").fetchone()

    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")


def test_gmail_mailbox_cache_rebuilds_legacy_thread_pages_schema(tmp_path):
    cache_path = tmp_path / "legacy_gmail_mailbox_cache.sqlite3"
    connection = sqlite3.connect(cache_path)
    connection.execute(
        """
        CREATE TABLE gmail_thread_pages (
            account_email TEXT NOT NULL,
            query TEXT NOT NULL,
            page_key TEXT NOT NULL,
            thread_ids_json TEXT NOT NULL,
            next_page_token TEXT,
            has_more INTEGER NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (account_email, query, page_key)
        )
        """
    )
    connection.commit()
    connection.close()

    cache = GmailMailboxCache(str(cache_path))
    cache.store_thread_page(
        "user@gmail.com",
        mailbox_key="inbox",
        unread_only=False,
        page=ThreadSummaryPage(
            threads=[
                ThreadSummary(
                    id="thread-1",
                    subject="Migrated cache",
                    snippet="Migrated cache",
                    participants=["founder@example.com", "user@gmail.com"],
                    last_message_at=datetime.now(UTC),
                    action_states=[ActionState.FYI],
                )
            ],
            next_page_token=None,
            has_more=False,
            total_count=1,
        ),
    )

    with cache._connect() as connection:
        columns = connection.execute("PRAGMA table_info(gmail_thread_pages)").fetchall()

    assert [column["name"] for column in columns] == [
        "account_email",
        "mailbox_key",
        "unread_only",
        "query",
        "page_key",
        "thread_ids_json",
        "next_page_token",
        "has_more",
        "total_count",
        "updated_at",
    ]


def test_google_client_lists_thread_summaries_without_full_thread_hydration(
    monkeypatch,
):
    google_client = get_google_workspace_client()
    summary_payloads = {
        "thread-1": {
            "id": "thread-1",
            "snippet": "First snippet",
            "messages": [
                {
                    "id": "message-1",
                    "internalDate": str(int(datetime.now(UTC).timestamp() * 1000)),
                    "labelIds": ["INBOX", "UNREAD"],
                    "payload": {
                        "headers": [
                            {"name": "Subject", "value": "First subject"},
                            {"name": "From", "value": "Founder <founder@example.com>"},
                            {"name": "To", "value": "user@gmail.com"},
                        ]
                    },
                }
            ],
        }
    }

    def fake_request(method: str, url: str, **kwargs):
        if url.endswith("/threads"):
            return {
                "threads": [{"id": "thread-1"}],
                "nextPageToken": "next-page",
                "resultSizeEstimate": 37,
            }
        if url.endswith("/threads/thread-1"):
            return summary_payloads["thread-1"]
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr(google_client, "_request", fake_request)
    monkeypatch.setattr(
        google_client,
        "get_gmail_thread",
        lambda access_token, thread_id: (_ for _ in ()).throw(
            AssertionError("list_gmail_threads should not call get_gmail_thread")
        ),
    )

    page = google_client.list_gmail_threads("access-token", max_results=20)

    assert page.next_page_token == "next-page"
    assert page.has_more is True
    assert page.total_count == 37
    assert page.threads[0].id == "thread-1"
    assert page.threads[0].subject == "First subject"
    assert page.threads[0].participants[0] == "founder@example.com"


def test_google_client_compose_uses_refetched_sent_message(monkeypatch):
    google_client = get_google_workspace_client()
    sent_thread = ThreadDetail(
        id="thread-1",
        subject="Launch plan",
        snippet="Latest reply",
        participants=["founder@example.com", "user@gmail.com"],
        last_message_at=datetime.now(UTC),
        action_states=[ActionState.FYI],
        messages=[
            ThreadMessage(
                id="message-older",
                sender="founder@example.com",
                sent_at=datetime.now(UTC) - timedelta(hours=1),
                body="Can you confirm?",
            ),
            ThreadMessage(
                id="message-sent",
                sender="user@gmail.com",
                sent_at=datetime.now(UTC),
                body="Confirmed.",
            ),
        ],
        analysis=None,
    )

    thread_payload = {
        "id": "thread-1",
        "messages": [
            {
                "id": "message-older",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "Founder <founder@example.com>"},
                        {"name": "To", "value": "user@gmail.com"},
                        {"name": "Subject", "value": "Launch plan"},
                        {"name": "Message-Id", "value": "<message-older@example.com>"},
                    ]
                },
            }
        ],
    }

    monkeypatch.setattr(
        google_client,
        "_get_gmail_thread_payload",
        lambda access_token, thread_id: thread_payload,
    )
    monkeypatch.setattr(
        google_client,
        "get_gmail_thread",
        lambda access_token, thread_id: sent_thread,
    )
    monkeypatch.setattr(
        google_client,
        "_request",
        lambda method, url, **kwargs: {"id": "gmail-api-message-id"},
    )

    result = google_client.compose_gmail_thread(
        "access-token",
        account_email="user@gmail.com",
        thread_id="thread-1",
        payload=ComposeThreadRequest(mode=ComposeMode.REPLY, body="Confirmed."),
    )

    assert result.thread == sent_thread
    assert result.sent_message == sent_thread.messages[-1]


def test_google_client_forward_refetches_new_thread(monkeypatch):
    google_client = get_google_workspace_client()
    captured: dict[str, str] = {}
    sent_thread = ThreadDetail(
        id="forwarded-thread",
        subject="Fwd: Launch plan",
        snippet="Please see below.",
        participants=["ops@example.com", "user@gmail.com"],
        last_message_at=datetime.now(UTC),
        action_states=[ActionState.FYI],
        messages=[
            ThreadMessage(
                id="forwarded-message",
                sender="user@gmail.com",
                sent_at=datetime.now(UTC),
                body="Please see below.",
            )
        ],
        analysis=None,
    )
    thread_payload = {
        "id": "thread-1",
        "messages": [
            {
                "id": "message-older",
                "internalDate": str(int(datetime.now(UTC).timestamp() * 1000)),
                "payload": {
                    "headers": [
                        {"name": "From", "value": "Founder <founder@example.com>"},
                        {"name": "To", "value": "user@gmail.com"},
                        {"name": "Subject", "value": "Launch plan"},
                        {"name": "Message-Id", "value": "<message-older@example.com>"},
                    ]
                },
            }
        ],
    }

    monkeypatch.setattr(
        google_client,
        "_get_gmail_thread_payload",
        lambda access_token, thread_id: thread_payload,
    )

    def get_thread(access_token: str, thread_id: str) -> ThreadDetail:
        captured["thread_id"] = thread_id
        return sent_thread

    monkeypatch.setattr(google_client, "get_gmail_thread", get_thread)
    monkeypatch.setattr(
        google_client,
        "_request",
        lambda method, url, **kwargs: {
            "id": "gmail-api-message-id",
            "threadId": "forwarded-thread",
        },
    )

    result = google_client.compose_gmail_thread(
        "access-token",
        account_email="user@gmail.com",
        thread_id="thread-1",
        payload=ComposeThreadRequest(
            mode=ComposeMode.FORWARD,
            body="Please see below.",
            to=["ops@example.com"],
        ),
    )

    assert captured["thread_id"] == "forwarded-thread"
    assert result.thread == sent_thread
    assert result.sent_message == sent_thread.messages[-1]


def test_google_client_returns_total_count_for_empty_thread_page(monkeypatch):
    google_client = get_google_workspace_client()

    def fake_request(method: str, url: str, **kwargs):
        if url.endswith("/threads"):
            return {
                "threads": [],
                "resultSizeEstimate": 0,
            }
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr(google_client, "_request", fake_request)

    page = google_client.list_gmail_threads("access-token", max_results=20)

    assert page.threads == []
    assert page.has_more is False
    assert page.next_page_token is None
    assert page.total_count == 0


def test_google_client_returns_mailbox_counts_from_labels(monkeypatch):
    google_client = get_google_workspace_client()

    def fake_request(method: str, url: str, **kwargs):
        if url.endswith("/labels/INBOX"):
            return {"id": "INBOX", "threadsTotal": 1524}
        if url.endswith("/labels/SENT"):
            return {"id": "SENT", "threadsTotal": 201}
        if url.endswith("/labels/TRASH"):
            return {"id": "TRASH", "threadsTotal": 8}
        if url.endswith("/labels/SPAM"):
            return {"id": "SPAM", "threadsTotal": 2}
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr(google_client, "_request", fake_request)

    counts = google_client.get_gmail_mailbox_counts("access-token")

    assert counts.inbox == 1524
    assert counts.sent == 201
    assert counts.archive is None
    assert counts.trash == 8
    assert counts.junk == 2


def test_google_client_returns_null_for_missing_mailbox_label_totals(monkeypatch):
    google_client = get_google_workspace_client()

    def fake_request(method: str, url: str, **kwargs):
        if url.endswith("/labels/INBOX"):
            return {"id": "INBOX"}
        if url.endswith("/labels/SENT"):
            return {"id": "SENT", "threadsTotal": "201"}
        if url.endswith("/labels/TRASH"):
            return {"id": "TRASH"}
        if url.endswith("/labels/SPAM"):
            return {"id": "SPAM"}
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr(google_client, "_request", fake_request)

    counts = google_client.get_gmail_mailbox_counts("access-token")

    assert counts.inbox is None
    assert counts.sent == 201
    assert counts.archive is None
    assert counts.trash is None
    assert counts.junk is None


def test_google_client_extracts_html_body_breaks():
    google_client = get_google_workspace_client()

    body = google_client._extract_message_body(
        {
            "mimeType": "text/html",
            "body": {
                "data": encode_gmail_body(
                    "<div>Line one<br/>Line two<br />Line three</div>"
                )
            },
        }
    )

    assert body == "Line one\nLine two\nLine three"


def test_google_client_reply_uses_latest_non_self_sender(monkeypatch):
    google_client = get_google_workspace_client()
    sent: dict[str, str] = {}
    sent_thread = ThreadDetail(
        id="thread-1",
        subject="Re: Launch plan",
        snippet="Thanks for confirming",
        participants=["founder@example.com", "user@gmail.com"],
        last_message_at=datetime.now(UTC),
        action_states=[ActionState.FYI],
        messages=[
            ThreadMessage(
                id="message-older",
                sender="founder@example.com",
                sent_at=datetime.now(UTC) - timedelta(hours=1),
                body="Can you confirm?",
            ),
            ThreadMessage(
                id="message-sent",
                sender="user@gmail.com",
                sent_at=datetime.now(UTC),
                body="Confirmed.",
            ),
        ],
        analysis=None,
    )
    thread_payload = {
        "id": "thread-1",
        "messages": [
            {
                "id": "message-older",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "Founder <founder@example.com>"},
                        {"name": "To", "value": "user@gmail.com"},
                        {"name": "Subject", "value": "Launch plan"},
                        {"name": "Message-Id", "value": "<message-older@example.com>"},
                    ]
                },
            },
            {
                "id": "message-sent",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "User <user@gmail.com>"},
                        {"name": "To", "value": "Founder <founder@example.com>"},
                        {"name": "Subject", "value": "Re: Launch plan"},
                        {"name": "Message-Id", "value": "<message-sent@example.com>"},
                        {"name": "References", "value": "<message-older@example.com>"},
                    ]
                },
            },
        ],
    }

    monkeypatch.setattr(
        google_client,
        "_get_gmail_thread_payload",
        lambda access_token, thread_id: thread_payload,
    )
    monkeypatch.setattr(
        google_client,
        "get_gmail_thread",
        lambda access_token, thread_id: sent_thread,
    )

    def fake_request(method: str, url: str, **kwargs):
        if method == "POST" and url.endswith("/messages/send"):
            sent["raw"] = kwargs["json"]["raw"]
            sent["threadId"] = kwargs["json"]["threadId"]
            return {"id": "gmail-api-message-id"}
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr(google_client, "_request", fake_request)

    result = google_client.compose_gmail_thread(
        "access-token",
        account_email="user@gmail.com",
        thread_id="thread-1",
        payload=ComposeThreadRequest(mode=ComposeMode.REPLY, body="Confirmed."),
    )

    assert result.thread == sent_thread
    assert result.sent_message == sent_thread.messages[-1]
    assert sent["threadId"] == "thread-1"

    raw_message = base64.urlsafe_b64decode(
        sent["raw"] + "=" * (-len(sent["raw"]) % 4)
    ).decode("utf-8")
    assert "To: founder@example.com" in raw_message
    assert "In-Reply-To: <message-sent@example.com>" in raw_message


def test_gmail_mailbox_cache_round_trips_total_count_for_empty_page(tmp_path):
    cache = GmailMailboxCache(str(tmp_path / "gmail_mailbox_cache.sqlite3"))

    cache.store_thread_page(
        "user@gmail.com",
        mailbox_key="inbox",
        unread_only=False,
        page=ThreadSummaryPage(
            threads=[],
            next_page_token=None,
            has_more=False,
            total_count=0,
        ),
        page_key=None,
    )

    cached_page = cache.get_thread_page(
        "user@gmail.com",
        mailbox_key="inbox",
        unread_only=False,
        page_key=None,
    )

    assert cached_page is not None
    assert cached_page.threads == []
    assert cached_page.total_count == 0
    assert cached_page.has_more is False


def test_gmail_mailbox_cache_migrates_existing_page_table(tmp_path):
    db_path = tmp_path / "legacy_gmail_mailbox_cache.sqlite3"

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE gmail_thread_pages (
                account_email TEXT NOT NULL,
                mailbox_key TEXT NOT NULL,
                unread_only INTEGER NOT NULL,
                query TEXT NOT NULL,
                page_key TEXT NOT NULL,
                thread_ids_json TEXT NOT NULL,
                next_page_token TEXT,
                has_more INTEGER NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (
                    account_email,
                    mailbox_key,
                    unread_only,
                    query,
                    page_key
                )
            )
            """
        )
        connection.commit()

    cache = GmailMailboxCache(str(db_path))
    cache.store_thread_page(
        "user@gmail.com",
        mailbox_key="inbox",
        unread_only=False,
        page=ThreadSummaryPage(
            threads=[],
            next_page_token=None,
            has_more=False,
            total_count=12,
        ),
        page_key=None,
    )

    cached_page = cache.get_thread_page(
        "user@gmail.com",
        mailbox_key="inbox",
        unread_only=False,
        page_key=None,
    )

    assert cached_page is not None
    assert cached_page.total_count == 12


def test_opening_gmail_thread_updates_detail_cache(client, monkeypatch):
    auth_store = get_auth_store()
    session = build_session()
    auth_store.upsert_session(session)
    client.cookies.set(
        get_settings().session_cookie_name,
        session.session_id,
        domain="testserver.local",
    )

    google_client = get_google_workspace_client()
    thread = ThreadDetail(
        id="gmail-thread-2",
        subject="Cached detail",
        snippet="Detail payload",
        participants=["founder@gmail.com", "user@gmail.com"],
        last_message_at=datetime.now(UTC),
        action_states=[ActionState.FYI],
        messages=[
            ThreadMessage(
                id="gmail-message-2",
                sender="founder@gmail.com",
                sent_at=datetime.now(UTC),
                body="Detail payload",
                body_html='<div><p>Detail payload</p><img src="cid:hero.png"></div>',
                inline_assets=[
                    ThreadInlineAsset(
                        content_id="hero.png",
                        mime_type="image/png",
                        data_url="data:image/png;base64,AAAA",
                    )
                ],
            )
        ],
        analysis=None,
    )
    monkeypatch.setattr(
        google_client, "get_gmail_thread", lambda access_token, thread_id: thread
    )

    response = client.get("/gmail/threads/gmail-thread-2")

    assert response.status_code == 200
    payload = response.json()
    assert payload["messages"][0]["body_html"] == (
        '<div><p>Detail payload</p><img src="cid:hero.png"></div>'
    )
    assert payload["messages"][0]["inline_assets"] == [
        {
            "content_id": "hero.png",
            "mime_type": "image/png",
            "data_url": "data:image/png;base64,AAAA",
        }
    ]
    cached_thread = get_gmail_mailbox_cache().get_thread_detail(
        session.account_email,
        "gmail-thread-2",
    )
    assert cached_thread is not None
    assert cached_thread.id == "gmail-thread-2"
    assert cached_thread.messages[0].body_html == payload["messages"][0]["body_html"]
