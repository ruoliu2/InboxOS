import sqlite3
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.core.config import get_settings
from app.integrations.google_workspace import GoogleAPIError
from app.schemas.calendar import CalendarEvent
from app.schemas.common import ActionState
from app.schemas.thread import (
    ComposeMode,
    ComposeThreadRequest,
    ThreadDetail,
    ThreadMessage,
    ThreadSummary,
    ThreadSummaryPage,
)
from app.services.dependencies import (
    get_auth_service,
    get_auth_store,
    get_gmail_mailbox_cache,
    get_google_workspace_client,
)
from app.storage.auth_store import AuthSessionRecord
from app.storage.mailbox_cache import GmailMailboxCache


def build_session(**overrides: object) -> AuthSessionRecord:
    now = datetime.now(UTC)
    values: dict[str, object] = {
        "session_id": "session-1",
        "provider": "google",
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


def restart_auth_dependencies() -> None:
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
    client.cookies.set(get_settings().session_cookie_name, session.session_id)

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
    client.cookies.set(get_settings().session_cookie_name, session.session_id)

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
    client.cookies.set(get_settings().session_cookie_name, session.session_id)

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
    client.cookies.set(get_settings().session_cookie_name, session.session_id)

    response = client.get("/auth/session")

    assert response.status_code == 200
    assert response.json()["authenticated"] is False
    assert auth_store.get_session(session.session_id) is None


def test_refresh_failure_returns_401_and_deletes_session(client, monkeypatch):
    auth_store = get_auth_store()
    session = build_session(expires_at=datetime.now(UTC) - timedelta(minutes=1))
    auth_store.upsert_session(session)
    client.cookies.set(get_settings().session_cookie_name, session.session_id)

    google_client = get_google_workspace_client()
    monkeypatch.setattr(
        google_client,
        "refresh_access_token",
        lambda refresh_token: (_ for _ in ()).throw(RuntimeError("refresh failed")),
    )

    response = client.get("/gmail/threads")

    assert response.status_code == 401
    assert auth_store.get_session(session.session_id) is None


def test_logout_removes_persisted_session_and_clears_cookie(client):
    auth_store = get_auth_store()
    session = build_session()
    auth_store.upsert_session(session)
    client.cookies.set(get_settings().session_cookie_name, session.session_id)

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
    client.cookies.set(get_settings().session_cookie_name, session.session_id)

    google_client = get_google_workspace_client()
    monkeypatch.setattr(
        google_client,
        "list_gmail_threads",
        lambda access_token, **_: ThreadSummaryPage(
            threads=[],
            next_page_token=None,
            has_more=False,
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
    client.cookies.set(get_settings().session_cookie_name, session.session_id)

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

    monkeypatch.setattr(google_client, "list_gmail_threads", raise_disabled_error)

    response = client.get("/gmail/threads")

    assert response.status_code == 503
    assert "Gmail API is disabled" in response.json()["detail"]


def test_gmail_and_calendar_routes_use_google_client(client, monkeypatch):
    auth_store = get_auth_store()
    session = build_session()
    auth_store.upsert_session(session)
    client.cookies.set(get_settings().session_cookie_name, session.session_id)

    google_client = get_google_workspace_client()
    monkeypatch.setattr(
        google_client,
        "list_gmail_threads",
        lambda access_token, **_: ThreadSummaryPage(
            threads=[
                ThreadSummary(
                    id="gmail-thread-1",
                    subject="Launch checklist",
                    snippet="Please confirm the launch checklist.",
                    participants=["founder@gmail.com", "user@gmail.com"],
                    last_message_at=datetime.now(UTC),
                    action_states=[ActionState.TO_REPLY],
                )
            ],
            next_page_token="next-page",
            has_more=True,
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
    client.cookies.set(get_settings().session_cookie_name, session.session_id)

    cache = get_gmail_mailbox_cache()
    cache.store_thread_page(
        session.account_email,
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

    monkeypatch.setattr(google_client, "list_gmail_threads", fail_live_fetch)

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
    client.cookies.set(get_settings().session_cookie_name, session.session_id)

    cache = get_gmail_mailbox_cache()
    cache.store_thread_page(
        session.account_email,
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

    monkeypatch.setattr(google_client, "list_gmail_threads", fail_live_fetch)

    response = client.get("/gmail/threads")

    assert response.status_code == 200
    assert response.json()["threads"] == []
    assert response.json()["total_count"] == 0


def test_gmail_route_forwards_pagination_options(client, monkeypatch):
    auth_store = get_auth_store()
    session = build_session()
    auth_store.upsert_session(session)
    client.cookies.set(get_settings().session_cookie_name, session.session_id)

    google_client = get_google_workspace_client()
    captured: dict[str, object] = {}

    def list_threads(
        access_token: str,
        *,
        max_results: int = 20,
        page_token: str | None = None,
        mailbox=None,
        unread_only: bool = False,
        query: str | None = None,
    ) -> ThreadSummaryPage:
        captured["max_results"] = max_results
        captured["page_token"] = page_token
        captured["mailbox"] = mailbox.value if mailbox is not None else None
        captured["unread_only"] = unread_only
        captured["query"] = query
        return ThreadSummaryPage(
            threads=[],
            next_page_token=None,
            has_more=False,
        )

    monkeypatch.setattr(google_client, "list_gmail_threads", list_threads)

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
    client.cookies.set(get_settings().session_cookie_name, session.session_id)

    google_client = get_google_workspace_client()
    captured: dict[str, object] = {}

    def list_threads(access_token: str, **kwargs) -> ThreadSummaryPage:
        captured.update(kwargs)
        return ThreadSummaryPage(threads=[], next_page_token=None, has_more=False)

    monkeypatch.setattr(google_client, "list_gmail_threads", list_threads)

    response = client.get(
        "/gmail/threads?mailbox=archive&unread_only=true&q=label:team"
    )

    assert response.status_code == 200
    assert captured["mailbox"].value == "archive"
    assert captured["unread_only"] is True
    assert captured["query"] == "label:team"


def test_compose_route_updates_detail_cache_and_response(client, monkeypatch):
    auth_store = get_auth_store()
    session = build_session()
    auth_store.upsert_session(session)
    client.cookies.set(get_settings().session_cookie_name, session.session_id)

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


def test_thread_action_route_invalidates_cached_pages(client, monkeypatch):
    auth_store = get_auth_store()
    session = build_session()
    auth_store.upsert_session(session)
    client.cookies.set(get_settings().session_cookie_name, session.session_id)

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
    client.cookies.set(get_settings().session_cookie_name, session.session_id)

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
    client.cookies.set(get_settings().session_cookie_name, session.session_id)

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
            )
        ],
        analysis=None,
    )
    monkeypatch.setattr(
        google_client, "get_gmail_thread", lambda access_token, thread_id: thread
    )

    response = client.get("/gmail/threads/gmail-thread-2")

    assert response.status_code == 200
    cached_thread = get_gmail_mailbox_cache().get_thread_detail(
        session.account_email,
        "gmail-thread-2",
    )
    assert cached_thread is not None
    assert cached_thread.id == "gmail-thread-2"
