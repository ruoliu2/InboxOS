from datetime import UTC, datetime, timedelta, timezone

import pytest
from fastapi import Response

from app.core.config import get_settings
from app.services.dependencies import (
    get_auth_service,
    get_auth_store,
    get_google_workspace_client,
)
from app.storage.auth_store import AuthSessionRecord


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


def mock_google_login(
    monkeypatch: pytest.MonkeyPatch,
    *,
    email: str,
    name: str,
) -> None:
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
                "access_token": f"access-token-{email}",
                "refresh_token": f"refresh-token-{email}",
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
                "email": email,
                "name": name,
                "picture": None,
            },
        )(),
    )


def test_auth_session_returns_user_and_linked_accounts(client, monkeypatch):
    mock_google_login(monkeypatch, email="user@gmail.com", name="Inbox User")

    start_response = client.get("/auth/google/start?redirect_to=/mail")
    state = start_response.json()["state"]

    callback_response = client.get(
        f"/auth/google/callback?code=test-code&state={state}",
        follow_redirects=False,
    )
    assert callback_response.status_code == 303

    response = client.get("/auth/session")
    assert response.status_code == 200
    payload = response.json()
    assert payload["authenticated"] is True
    assert payload["user"]["primary_email"] == "user@gmail.com"
    assert payload["provider"] == "google_gmail"
    assert payload["active_account_id"] is not None
    assert len(payload["linked_accounts"]) == 1
    assert payload["linked_accounts"][0]["provider_account_ref"] == "user@gmail.com"


def test_link_second_google_account_reuses_existing_user(client, monkeypatch):
    auth_store = get_auth_store()
    initial_session = build_session()
    auth_store.upsert_session(initial_session)
    stored_session = auth_store.get_session(initial_session.session_id)
    assert stored_session is not None
    client.cookies.set(
        get_settings().session_cookie_name,
        stored_session.session_id,
        domain="testserver.local",
    )

    mock_google_login(monkeypatch, email="ops@gmail.com", name="Ops User")
    start_response = client.post(
        "/accounts/google_gmail/connect/start?redirect_to=/mail"
    )
    assert start_response.status_code == 200
    state = start_response.json()["state"]

    callback_response = client.get(
        f"/accounts/google_gmail/callback?code=test-code&state={state}",
        follow_redirects=False,
    )
    assert callback_response.status_code == 303

    current_session_id = callback_response.cookies.get(
        get_settings().session_cookie_name
    )
    assert current_session_id is not None
    linked_session = auth_store.get_session(current_session_id)
    assert linked_session is not None
    assert linked_session.user_id == stored_session.user_id

    linked_accounts = auth_store.list_linked_accounts(stored_session.user_id)
    assert len(linked_accounts) == 2
    assert {account.provider_account_ref for account in linked_accounts} == {
        "user@gmail.com",
        "ops@gmail.com",
    }


def test_activate_and_disconnect_linked_account(client):
    auth_store = get_auth_store()
    session = build_session()
    auth_store.upsert_session(session)
    stored_session = auth_store.get_session(session.session_id)
    assert stored_session is not None and stored_session.user_id is not None

    second_session = build_session(
        session_id="session-2",
        account_email="ops@gmail.com",
        account_name="Ops User",
    )
    second_session.user_id = stored_session.user_id
    auth_store.upsert_session(second_session)

    accounts = auth_store.list_linked_accounts(stored_session.user_id)
    assert len(accounts) == 2
    primary_account = next(
        account
        for account in accounts
        if account.provider_account_ref == "user@gmail.com"
    )
    secondary_account = next(
        account
        for account in accounts
        if account.provider_account_ref == "ops@gmail.com"
    )

    client.cookies.set(
        get_settings().session_cookie_name,
        stored_session.session_id,
        domain="testserver.local",
    )

    activate_response = client.post(f"/accounts/{secondary_account.id}/activate")
    assert activate_response.status_code == 200
    assert activate_response.json()["active_account_id"] == secondary_account.id

    disconnect_response = client.post(f"/accounts/{primary_account.id}/disconnect")
    assert disconnect_response.status_code == 204

    refreshed_accounts = auth_store.list_linked_accounts(stored_session.user_id)
    refreshed_primary = next(
        account for account in refreshed_accounts if account.id == primary_account.id
    )
    assert refreshed_primary.status == "disconnected"


def test_set_session_cookie_normalizes_expiry_to_utc():
    service = get_auth_service()
    response = Response()
    session = build_session(
        session_expires_at=datetime.now(timezone(timedelta(hours=-6))),
    )

    service.set_session_cookie(response, session)

    assert "set-cookie" in response.headers


def test_start_account_connect_rejects_missing_provider(client):
    response = client.post("/accounts/%20/connect/start?redirect_to=/mail")

    assert response.status_code == 422
    assert response.json()["detail"] == "provider is required"


def test_get_session_extends_ttl_without_full_session_upsert(monkeypatch):
    service = get_auth_service()
    store = get_auth_store()
    session = build_session()
    store.upsert_session(session)

    expiry_updates: list[tuple[str, datetime, datetime]] = []
    original_update_expiry = store.update_session_expiry

    monkeypatch.setattr(
        store,
        "upsert_session",
        lambda session: pytest.fail("unexpected full session upsert"),
    )

    def wrapped_update(
        session_id: str, session_expires_at: datetime, updated_at: datetime
    ) -> None:
        expiry_updates.append((session_id, session_expires_at, updated_at))
        original_update_expiry(session_id, session_expires_at, updated_at)

    monkeypatch.setattr(store, "update_session_expiry", wrapped_update)

    hydrated = service.get_session(session.session_id)

    assert hydrated is not None
    assert expiry_updates
    assert expiry_updates[0][0] == session.session_id
