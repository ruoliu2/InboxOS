from functools import lru_cache

from fastapi import Depends, HTTPException, Request, Response

from app.core.config import get_settings
from app.integrations.google_workspace import GoogleWorkspaceClient
from app.integrations.llm.openai_compatible import OpenAICompatibleAdapter
from app.integrations.mail.mailcore_adapter import MailcoreAdapter
from app.services.action_service import ActionService
from app.services.auth_service import AuthService
from app.services.sync_service import SyncService
from app.services.task_service import TaskService
from app.services.thread_service import ThreadService
from app.storage.auth_store import AuthSessionRecord, SQLiteAuthStore
from app.storage.mailbox_cache import GmailMailboxCache
from app.storage.store import get_store


@lru_cache
def get_action_service() -> ActionService:
    return ActionService()


@lru_cache
def get_thread_service() -> ThreadService:
    return ThreadService(get_store(), OpenAICompatibleAdapter())


@lru_cache
def get_task_service() -> TaskService:
    return TaskService(get_store())


@lru_cache
def get_sync_service() -> SyncService:
    return SyncService(
        get_store(),
        MailcoreAdapter(),
        get_thread_service(),
        get_task_service(),
    )


@lru_cache
def get_google_workspace_client() -> GoogleWorkspaceClient:
    return GoogleWorkspaceClient(get_settings())


@lru_cache
def get_gmail_mailbox_cache() -> GmailMailboxCache:
    return GmailMailboxCache(get_settings().gmail_cache_db_path)


@lru_cache
def get_auth_store() -> SQLiteAuthStore:
    settings = get_settings()
    return SQLiteAuthStore(
        settings.session_db_path,
        settings.oauth_state_ttl_seconds,
    )


@lru_cache
def get_auth_service() -> AuthService:
    return AuthService(get_auth_store(), get_google_workspace_client(), get_settings())


def get_current_auth_session(
    response: Response,
    request: Request,
    service: AuthService = Depends(get_auth_service),
) -> AuthSessionRecord:
    session_id = request.cookies.get(get_settings().session_cookie_name)
    session = service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    service.set_session_cookie(response, session)
    return session
