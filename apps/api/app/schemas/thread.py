from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import ActionState


class ThreadInlineAsset(BaseModel):
    content_id: str
    mime_type: str
    data_url: str


class ThreadMessage(BaseModel):
    id: str
    sender: str
    sent_at: datetime
    body: str
    body_html: str | None = None
    inline_assets: list[ThreadInlineAsset] = Field(default_factory=list)


class ThreadSummaryFields(BaseModel):
    id: str
    subject: str
    snippet: str
    participants: list[str]
    last_message_at: datetime
    action_states: list[ActionState]


class ThreadSummary(ThreadSummaryFields):
    state: Literal["ready"] = "ready"


class ThreadPlaceholder(BaseModel):
    state: Literal["placeholder"] = "placeholder"
    id: str


ThreadListItem = Annotated[
    ThreadPlaceholder | ThreadSummary, Field(discriminator="state")
]


class ThreadSummaryPage(BaseModel):
    threads: list[ThreadListItem] = Field(default_factory=list)
    next_page_token: str | None = None
    has_more: bool = False
    total_count: int | None = None
    hydrated_count: int = 0
    source: str = "live"
    synced_at: datetime | None = None


class MailboxCountsResponse(BaseModel):
    inbox: int | None = None
    sent: int | None = None
    archive: int | None = None
    trash: int | None = None
    junk: int | None = None


class MailboxKey(StrEnum):
    INBOX = "inbox"
    SENT = "sent"
    ARCHIVE = "archive"
    TRASH = "trash"
    JUNK = "junk"


class ThreadAnalysis(BaseModel):
    summary: str
    action_items: list[str] = Field(default_factory=list)
    deadlines: list[str] = Field(default_factory=list)
    requested_items: list[str] = Field(default_factory=list)
    recommended_next_action: str
    action_states: list[ActionState] = Field(default_factory=list)
    analyzed_at: datetime


class ThreadDetail(ThreadSummaryFields):
    messages: list[ThreadMessage]
    analysis: ThreadAnalysis | None = None


class ThreadHydrateRequest(BaseModel):
    thread_ids: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("thread_ids")
    @classmethod
    def validate_thread_ids(cls, value: list[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for thread_id in value:
            normalized = thread_id.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(normalized)
        return ordered


class ThreadHydrateResponse(BaseModel):
    threads: dict[str, ThreadSummary] = Field(default_factory=dict)
    hydrated_count: int = 0
    synced_at: datetime | None = None


class ReplyToThreadRequest(BaseModel):
    body: str = Field(min_length=1)
    mute_thread: bool = False

    @field_validator("body")
    @classmethod
    def validate_body(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Reply body must not be empty.")
        return normalized


class ReplyToThreadResponse(BaseModel):
    thread: ThreadDetail
    sent_message: ThreadMessage
    muted: bool


class ComposeMode(StrEnum):
    REPLY = "reply"
    REPLY_ALL = "reply_all"
    FORWARD = "forward"


class ComposeThreadRequest(BaseModel):
    mode: ComposeMode = ComposeMode.REPLY
    body: str = ""
    to: list[str] = Field(default_factory=list)
    cc: list[str] = Field(default_factory=list)
    bcc: list[str] = Field(default_factory=list)

    @field_validator("body")
    @classmethod
    def validate_body(cls, value: str) -> str:
        return value.strip()

    @field_validator("to", "cc", "bcc")
    @classmethod
    def validate_recipients(cls, value: list[str]) -> list[str]:
        recipients = [item.strip().lower() for item in value if item.strip()]
        if any("@" not in item for item in recipients):
            raise ValueError("Recipients must be email addresses.")
        return recipients

    @field_validator("bcc")
    @classmethod
    def validate_forward_requirements(cls, value: list[str], info) -> list[str]:
        mode = info.data.get("mode")
        recipients = info.data.get("to", [])
        if mode == ComposeMode.FORWARD and not recipients:
            raise ValueError("Forwarding requires at least one recipient.")
        if mode in (ComposeMode.REPLY, ComposeMode.REPLY_ALL) and value:
            raise ValueError("Reply modes do not support custom BCC recipients.")
        return value


class ComposeThreadResponse(BaseModel):
    thread: ThreadDetail
    sent_message: ThreadMessage
    mode: ComposeMode


class SendGmailMessageRequest(BaseModel):
    to: list[str] = Field(default_factory=list)
    subject: str = Field(min_length=1)
    body: str = ""

    @field_validator("to")
    @classmethod
    def validate_to(cls, value: list[str]) -> list[str]:
        recipients = [item.strip().lower() for item in value if item.strip()]
        if not recipients:
            raise ValueError("At least one recipient is required.")
        if any("@" not in item for item in recipients):
            raise ValueError("Recipients must be email addresses.")
        return recipients

    @field_validator("subject")
    @classmethod
    def validate_subject(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Subject must not be empty.")
        return normalized


class SendGmailMessageResponse(BaseModel):
    thread: ThreadDetail
    sent_message: ThreadMessage


class ThreadActionName(StrEnum):
    ARCHIVE = "archive"
    JUNK = "junk"
    TRASH = "trash"
    DELETE = "delete"
    RESTORE = "restore"


class ThreadActionRequest(BaseModel):
    action: ThreadActionName


class ThreadActionResponse(BaseModel):
    thread_id: str
    action: ThreadActionName
    thread: ThreadDetail | None = None
    deleted: bool = False
