from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.common import SyncStatus
from app.services.dependencies import get_gmail_mailbox_cache
from app.storage.store import get_store


@pytest.fixture(autouse=True)
def reset_store_state() -> None:
    store = get_store()
    store.threads = {}
    store.tasks = {}
    store.oauth_states = {}
    store.sessions = {}
    store.sync_status = {
        "sync_id": None,
        "status": SyncStatus.IDLE,
        "imported_threads": 0,
        "updated_at": datetime.now(UTC),
        "last_error": None,
    }
    get_gmail_mailbox_cache().clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
