from datetime import datetime

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


class ThreadSummary(BaseModel):
    id: str
    subject: str
    snippet: str
    participants: list[str]
    last_message_at: datetime
    action_states: list[ActionState]


class ThreadSummaryPage(BaseModel):
    threads: list[ThreadSummary] = Field(default_factory=list)
    next_page_token: str | None = None
    has_more: bool = False


class ThreadAnalysis(BaseModel):
    summary: str
    action_items: list[str] = Field(default_factory=list)
    deadlines: list[str] = Field(default_factory=list)
    requested_items: list[str] = Field(default_factory=list)
    recommended_next_action: str
    action_states: list[ActionState] = Field(default_factory=list)
    analyzed_at: datetime


class ThreadDetail(ThreadSummary):
    messages: list[ThreadMessage]
    analysis: ThreadAnalysis | None = None


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
