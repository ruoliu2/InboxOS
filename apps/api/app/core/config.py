from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

API_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = API_ROOT.parents[1]


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
    google_redirect_uri: str = "http://localhost:8000/auth/google/callback"
    gmail_cache_db_path: str = str(
        Path.home() / ".cache" / "inboxos" / "gmail_mailbox_cache.sqlite3"
    )
    tasks_database_url: str = (
        f"sqlite:///{Path.home() / '.cache' / 'inboxos' / 'tasks.sqlite3'}"
    )
    openai_api_base: str | None = None
    openai_api_key: str | None = None

    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", API_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
