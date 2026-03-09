from functools import lru_cache

from fastapi import Depends, HTTPException, Request, Response

from app.core.config import get_settings
from app.integrations.google_workspace import GoogleWorkspaceClient
from app.services.auth_service import AuthService
from app.services.gmail_mailbox_service import GmailMailboxService
from app.services.task_service import TaskService
from app.storage.auth_store import AuthSessionRecord, AuthStore, build_auth_store
from app.storage.conversation_store import ConversationStore, build_conversation_store
from app.storage.gmail_mailbox_store import GmailMailboxStore, build_gmail_mailbox_store
from app.storage.mailbox_cache import GmailMailboxCache
from app.storage.task_store import TaskStore, build_task_store


@lru_cache
def get_task_store() -> TaskStore:
    return build_task_store(get_settings().database_url)


@lru_cache
def get_conversation_store() -> ConversationStore:
    return build_conversation_store(get_settings().database_url)


@lru_cache
def get_task_service() -> TaskService:
    return TaskService(get_task_store(), get_conversation_store())


@lru_cache
def get_google_workspace_client() -> GoogleWorkspaceClient:
    return GoogleWorkspaceClient(get_settings())


@lru_cache
def get_gmail_mailbox_store() -> GmailMailboxStore:
    return build_gmail_mailbox_store(get_settings().database_url)


@lru_cache
def get_gmail_mailbox_cache() -> GmailMailboxCache:
    return GmailMailboxCache(get_settings().gmail_cache_db_path)


@lru_cache
def get_auth_store() -> AuthStore:
    settings = get_settings()
    return build_auth_store(
        settings.database_url,
        settings.oauth_state_ttl_seconds,
        settings.credential_encryption_key,
    )


@lru_cache
def get_auth_service() -> AuthService:
    return AuthService(
        get_auth_store(),
        get_google_workspace_client(),
        get_settings(),
    )


@lru_cache
def get_gmail_mailbox_service() -> GmailMailboxService:
    return GmailMailboxService(
        get_google_workspace_client(),
        get_gmail_mailbox_store(),
        get_auth_store(),
        get_settings(),
    )


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
