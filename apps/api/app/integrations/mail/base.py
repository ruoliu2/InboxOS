from collections.abc import Sequence
from typing import Protocol

from app.schemas.thread import ThreadDetail


class MailSyncAdapter(Protocol):
    def sync_threads(
        self, account_email: str | None = None
    ) -> Sequence[ThreadDetail]: ...
