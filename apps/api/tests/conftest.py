from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.common import SyncStatus
from app.storage.store import get_store


@pytest.fixture(autouse=True)
def reset_store_state() -> None:
    store = get_store()
    store.threads = {}
    store.tasks = {}
    store.sync_status = {
        "sync_id": None,
        "status": SyncStatus.IDLE,
        "imported_threads": 0,
        "updated_at": datetime.now(UTC),
        "last_error": None,
    }


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
