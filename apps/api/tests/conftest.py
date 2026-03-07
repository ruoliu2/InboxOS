import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.services.dependencies import (
    get_auth_service,
    get_auth_store,
    get_gmail_mailbox_cache,
    get_google_workspace_client,
)
from app.storage.store import get_store


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
    get_settings.cache_clear()
    get_auth_service.cache_clear()
    get_auth_store.cache_clear()
    get_gmail_mailbox_cache.cache_clear()
    get_google_workspace_client.cache_clear()

    store = get_store()
    store.tasks = {}
    get_auth_store().clear()
    get_gmail_mailbox_cache().clear()
    yield
    get_auth_service.cache_clear()
    get_auth_store.cache_clear()
    get_gmail_mailbox_cache.cache_clear()
    get_google_workspace_client.cache_clear()
    get_settings.cache_clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
