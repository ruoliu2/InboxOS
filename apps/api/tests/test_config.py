from pathlib import Path

from app.core.config import Settings, resolve_repo_root


def test_resolve_repo_root_prefers_monorepo_root():
    api_root = Path("/tmp/workspace/InboxOS/apps/api")

    assert resolve_repo_root(api_root) == Path("/tmp/workspace/InboxOS")


def test_resolve_repo_root_falls_back_to_api_root_for_container_layout():
    api_root = Path("/app")

    assert resolve_repo_root(api_root) == Path("/app")


def test_google_redirect_uri_defaults_to_localhost():
    settings = Settings(_env_file=None)

    assert settings.resolved_google_redirect_uri == (
        "http://localhost:8000/auth/google/callback"
    )


def test_google_redirect_uri_uses_railway_public_domain(monkeypatch):
    monkeypatch.setenv("RAILWAY_PUBLIC_DOMAIN", "api-production-136b.up.railway.app")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "")
    settings = Settings(_env_file=None)

    assert settings.resolved_google_redirect_uri == (
        "https://api-production-136b.up.railway.app/auth/google/callback"
    )
