from pathlib import Path

from app.core.config import resolve_repo_root


def test_resolve_repo_root_prefers_monorepo_root():
    api_root = Path("/tmp/workspace/InboxOS/apps/api")

    assert resolve_repo_root(api_root) == Path("/tmp/workspace/InboxOS")


def test_resolve_repo_root_falls_back_to_api_root_for_container_layout():
    api_root = Path("/app")

    assert resolve_repo_root(api_root) == Path("/app")
