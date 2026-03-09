import os
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("CREDENTIAL_ENCRYPTION_KEY", "test-encryption-key")

from app.core.config import get_settings
from app.main import app
from app.services.dependencies import (
    get_auth_service,
    get_auth_store,
    get_conversation_store,
    get_gmail_mailbox_cache,
    get_google_workspace_client,
    get_openai_compatible_client,
    get_task_service,
    get_task_store,
    get_thread_analysis_service,
)
from app.storage.auth_store import AuthSessionRecord


@pytest.fixture(autouse=True)
def reset_store_state(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv(
        "SESSION_DB_PATH",
        str(tmp_path / "auth_sessions.sqlite3"),
    )
    monkeypatch.setenv(
        "GMAIL_CACHE_DB_PATH",
        str(tmp_path / "gmail_mailbox_cache.sqlite3"),
    )
    monkeypatch.setenv(
        "DATABASE_URL",
        f"sqlite:///{tmp_path / 'tasks.sqlite3'}",
    )
    monkeypatch.delenv("TASKS_DATABASE_URL", raising=False)
    monkeypatch.setenv(
        "CREDENTIAL_ENCRYPTION_KEY",
        "test-encryption-key",
    )
    get_settings.cache_clear()
    get_auth_service.cache_clear()
    get_auth_store.cache_clear()
    get_conversation_store.cache_clear()
    get_gmail_mailbox_cache.cache_clear()
    get_google_workspace_client.cache_clear()
    get_openai_compatible_client.cache_clear()
    get_task_store.cache_clear()
    get_task_service.cache_clear()
    get_thread_analysis_service.cache_clear()
    get_auth_store().clear()
    get_conversation_store().clear()
    get_gmail_mailbox_cache().clear()
    get_task_store().clear()
    yield
    get_auth_service.cache_clear()
    get_auth_store.cache_clear()
    get_conversation_store.cache_clear()
    get_gmail_mailbox_cache.cache_clear()
    get_google_workspace_client.cache_clear()
    get_openai_compatible_client.cache_clear()
    get_task_store.cache_clear()
    get_task_service.cache_clear()
    get_thread_analysis_service.cache_clear()
    get_settings.cache_clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


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


@pytest.fixture
def authenticated_client(client: TestClient) -> TestClient:
    session = build_session()
    get_auth_store().upsert_session(session)
    client.cookies.set(
        get_settings().session_cookie_name,
        session.session_id,
        domain="testserver.local",
    )
    return client
