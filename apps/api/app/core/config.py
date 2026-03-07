from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def resolve_repo_root(api_root: Path) -> Path:
    parents = api_root.parents
    if len(parents) >= 2:
        return parents[1]
    return api_root


def normalize_public_url(value: str | None, *, default_scheme: str) -> str | None:
    if value is None:
        return None

    normalized = value.strip().rstrip("/")
    if not normalized:
        return None
    if "://" in normalized:
        return normalized
    return f"{default_scheme}://{normalized}"


API_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = resolve_repo_root(API_ROOT)


class Settings(BaseSettings):
    app_name: str = "InboxOS API"
    app_env: str = "dev"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    cors_origins: str = "http://localhost:3000"
    web_base_url: str = "http://localhost:3000"
    session_cookie_name: str = "inboxos_session"
    session_cookie_secure: bool = False
    session_db_path: str = str(
        Path.home() / ".cache" / "inboxos" / "auth_sessions.sqlite3"
    )
    session_ttl_seconds: int = 60 * 60 * 24 * 30
    oauth_state_ttl_seconds: int = 60 * 15
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str | None = None
    railway_public_domain: str | None = None
    gmail_cache_db_path: str = str(
        Path.home() / ".cache" / "inboxos" / "gmail_mailbox_cache.sqlite3"
    )

    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", API_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def resolved_google_redirect_uri(self) -> str:
        explicit_redirect = normalize_public_url(
            self.google_redirect_uri,
            default_scheme="https",
        )
        if explicit_redirect is not None:
            return explicit_redirect

        railway_domain = normalize_public_url(
            self.railway_public_domain,
            default_scheme="https",
        )
        if railway_domain is not None:
            return f"{railway_domain}/auth/google/callback"

        return "http://localhost:8000/auth/google/callback"


@lru_cache
def get_settings() -> Settings:
    return Settings()
