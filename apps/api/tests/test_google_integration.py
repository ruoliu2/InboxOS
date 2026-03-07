import base64
import sqlite3
from datetime import UTC, datetime, timedelta

import httpx
import pytest

import app.storage.store as store_module
from app.integrations.google_workspace import GoogleAPIError
from app.schemas.calendar import CalendarEvent
from app.schemas.common import ActionState
from app.schemas.thread import (
    ThreadDetail,
    ThreadMessage,
    ThreadSummary,
    ThreadSummaryPage,
)
from app.services.dependencies import (
    get_gmail_mailbox_cache,
    get_google_workspace_client,
)
from app.storage.store import AuthSessionRecord


def build_session() -> AuthSessionRecord:
    now = datetime.now(UTC)
    return AuthSessionRecord(
        session_id="session-1",
        provider="google",
        account_email="user@gmail.com",
        account_name="Inbox User",
        account_picture=None,
        access_token="access-token",
        refresh_token="refresh-token",
        scope="email profile",
        expires_at=now + timedelta(hours=1),
        created_at=now,
        updated_at=now,
    )


def test_google_callback_sets_session_cookie_and_redirects(client, monkeypatch):
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

    start_response = client.get("/auth/google/start?redirect_to=/calendar")
    assert start_response.status_code == 200
    state = start_response.json()["state"]

    callback_response = client.get(
        f"/auth/google/callback?code=test-code&state={state}",
        follow_redirects=False,
    )
    assert callback_response.status_code == 303
    assert callback_response.headers["location"] == "http://localhost:3000/calendar"
    assert "inboxos_session=" in callback_response.headers["set-cookie"]

    session_response = client.get("/auth/session")
    assert session_response.status_code == 200
    assert session_response.json()["authenticated"] is True
    assert session_response.json()["account_email"] == "user@gmail.com"


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
    store = store_module.get_store()
    session = build_session()
    store.upsert_session(session)
    client.cookies.set("inboxos_session", session.session_id)

    google_client = get_google_workspace_client()

    def raise_disabled_error(
        access_token: str,
        *,
        max_results: int = 20,
        page_token: str | None = None,
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
    store = store_module.get_store()
    session = build_session()
    store.upsert_session(session)
    client.cookies.set("inboxos_session", session.session_id)

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

    thread_response = client.get("/gmail/threads/gmail-thread-1")
    assert thread_response.status_code == 200
    assert thread_response.json()["id"] == "gmail-thread-1"

    calendar_response = client.get("/calendar/events")
    assert calendar_response.status_code == 200
    assert calendar_response.json()[0]["title"] == "InboxOS Demo"


def test_gmail_route_returns_cached_first_page_before_refresh(client, monkeypatch):
    store = store_module.get_store()
    session = build_session()
    store.upsert_session(session)
    client.cookies.set("inboxos_session", session.session_id)

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
        ),
        page_key=None,
    )

    google_client = get_google_workspace_client()

    def fail_live_fetch(
        access_token: str,
        *,
        max_results: int = 20,
        page_token: str | None = None,
        query: str | None = None,
    ) -> ThreadSummaryPage:
        raise RuntimeError("live fetch should not block cached startup")

    monkeypatch.setattr(google_client, "list_gmail_threads", fail_live_fetch)

    response = client.get("/gmail/threads")

    assert response.status_code == 200
    assert response.json()["threads"][0]["id"] == "cached-thread-1"
    assert response.json()["next_page_token"] == "cached-next"


def test_gmail_route_forwards_pagination_options(client, monkeypatch):
    store = store_module.get_store()
    session = build_session()
    store.upsert_session(session)
    client.cookies.set("inboxos_session", session.session_id)

    google_client = get_google_workspace_client()
    captured: dict[str, object] = {}

    def list_threads(
        access_token: str,
        *,
        max_results: int = 20,
        page_token: str | None = None,
        query: str | None = None,
    ) -> ThreadSummaryPage:
        captured["max_results"] = max_results
        captured["page_token"] = page_token
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
        "query": "from:founder",
    }


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
            messages=[],
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


def test_calendar_route_preserves_explicit_time_window(client, monkeypatch):
    store = store_module.get_store()
    session = build_session()
    store.upsert_session(session)
    client.cookies.set("inboxos_session", session.session_id)

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
    assert page.threads[0].id == "thread-1"
    assert page.threads[0].subject == "First subject"
    assert page.threads[0].participants[0] == "founder@example.com"


def test_opening_gmail_thread_updates_detail_cache(client, monkeypatch):
    store = store_module.get_store()
    session = build_session()
    store.upsert_session(session)
    client.cookies.set("inboxos_session", session.session_id)

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
