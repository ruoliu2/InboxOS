from functools import lru_cache

from app.integrations.llm.openai_compatible import OpenAICompatibleAdapter
from app.integrations.mail.mailcore_adapter import MailcoreAdapter
from app.services.action_service import ActionService
from app.services.auth_service import AuthService
from app.services.sync_service import SyncService
from app.services.task_service import TaskService
from app.services.thread_service import ThreadService
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
def get_auth_service() -> AuthService:
    return AuthService()
