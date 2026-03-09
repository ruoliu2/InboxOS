from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, time, timedelta

from pydantic import BaseModel, Field, ValidationError

from app.integrations.openai_compatible import LLMError, OpenAICompatibleClient
from app.schemas.common import ActionState, DeadlineSource, TaskOrigin, TaskStatus
from app.schemas.task import TaskItem
from app.schemas.thread import (
    ExtractedDeadline,
    ExtractedTask,
    ThreadAnalysis,
    ThreadDetail,
)
from app.services.id_factory import new_id
from app.storage.conversation_store import (
    ConversationInsightRecord,
    ConversationRecord,
    ConversationStore,
    new_conversation_record,
)
from app.storage.task_store import TaskStore

ANALYSIS_PROMPT = """You analyze email threads for InboxOS.
Return strict JSON with these keys:
- summary: string
- action_items: string[]
- requested_items: string[]
- recommended_next_action: string
- action_states: array containing only to_reply, to_follow_up, task, fyi
- deadlines: array of objects with title, due_at, source_message_id
- extracted_tasks: array of objects with title, category, due_at, source_message_id

Rules:
- Use RFC3339 timestamps when a time is explicit.
- Use YYYY-MM-DD when only a date is explicit.
- Only include deadlines and tasks grounded in the thread.
- If no action state applies, return fyi.
- Categories should be one of reply, follow_up, deadline, task when possible.
"""


class RawExtractedDeadline(BaseModel):
    title: str
    due_at: str
    source_message_id: str | None = None


class RawExtractedTask(BaseModel):
    title: str
    category: str | None = None
    due_at: str | None = None
    source_message_id: str | None = None


class RawThreadAnalysis(BaseModel):
    summary: str
    action_items: list[str] = Field(default_factory=list)
    requested_items: list[str] = Field(default_factory=list)
    recommended_next_action: str
    action_states: list[ActionState] = Field(default_factory=list)
    deadlines: list[RawExtractedDeadline] = Field(default_factory=list)
    extracted_tasks: list[RawExtractedTask] = Field(default_factory=list)


def _normalize_category(value: str | None) -> str:
    normalized = (value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in {"reply", "follow_up", "deadline", "task"}:
        return normalized
    return "task"


def _parse_due_at(raw_value: str, *, default_tz=UTC) -> tuple[datetime, bool]:
    value = raw_value.strip()
    if not value:
        raise ValueError("due_at must not be empty")
    if len(value) == 10:
        parsed_date = date.fromisoformat(value)
        return datetime.combine(parsed_date, time(hour=17, tzinfo=default_tz)), True
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=default_tz)
    return parsed, False


class ThreadAnalysisService:
    def __init__(
        self,
        client: OpenAICompatibleClient,
        conversation_store: ConversationStore,
        task_store: TaskStore,
    ) -> None:
        self.client = client
        self.conversation_store = conversation_store
        self.task_store = task_store

    @property
    def enabled(self) -> bool:
        return self.client.enabled

    def analyze_thread(
        self,
        *,
        user_id: str,
        linked_account_id: str,
        provider: str,
        thread: ThreadDetail,
        timeout_seconds: float | None = None,
    ) -> ThreadDetail:
        if not self.enabled:
            return thread

        conversation = self.conversation_store.get_by_external_id(
            user_id,
            linked_account_id,
            thread.id,
        )
        if conversation is None:
            conversation = self.conversation_store.upsert_conversation(
                new_conversation_record(
                    user_id=user_id,
                    linked_account_id=linked_account_id,
                    provider=provider,
                    external_conversation_id=thread.id,
                    title=thread.subject,
                    preview=thread.snippet,
                    last_message_at=thread.last_message_at,
                    source_folder=None,
                )
            )

        messages = [
            {
                "id": message.id,
                "sender": message.sender,
                "sent_at": message.sent_at.isoformat(),
                "body": message.body,
            }
            for message in thread.messages
        ]
        content = self.client.create_chat_completion(
            messages=[
                {"role": "system", "content": ANALYSIS_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "thread_id": thread.id,
                            "subject": thread.subject,
                            "snippet": thread.snippet,
                            "last_message_at": thread.last_message_at.isoformat(),
                            "participants": thread.participants,
                            "messages": messages,
                        }
                    ),
                },
            ],
            response_format={"type": "json_object"},
            timeout_seconds=timeout_seconds,
        )
        analysis = self._parse_analysis_response(content, thread.last_message_at)
        insight = ConversationInsightRecord(
            conversation_id=conversation.id,
            summary=analysis.summary,
            action_items=list(analysis.action_items),
            deadlines=list(analysis.deadlines),
            extracted_tasks=list(analysis.extracted_tasks),
            requested_items=list(analysis.requested_items),
            recommended_next_action=analysis.recommended_next_action,
            action_states=[state.value for state in analysis.action_states],
            analyzed_at=analysis.analyzed_at,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.conversation_store.upsert_insight(insight)
        self._sync_agent_tasks(
            user_id=user_id,
            linked_account_id=linked_account_id,
            conversation=conversation,
            thread=thread,
            analysis=analysis,
        )
        thread.analysis = analysis
        thread.action_states = analysis.action_states or [ActionState.FYI]
        return thread

    def _parse_analysis_response(
        self,
        content: str,
        last_message_at: datetime,
    ) -> ThreadAnalysis:
        try:
            payload = RawThreadAnalysis.model_validate_json(content)
        except ValidationError as exc:
            raise LLMError(
                "LLM response did not match the expected analysis schema."
            ) from exc

        deadlines: list[ExtractedDeadline] = []
        for item in payload.deadlines:
            due_at, is_date_only = _parse_due_at(item.due_at)
            deadlines.append(
                ExtractedDeadline(
                    title=item.title.strip(),
                    due_at=due_at,
                    source_message_id=item.source_message_id,
                    is_date_only=is_date_only,
                )
            )

        extracted_tasks: list[ExtractedTask] = []
        for item in payload.extracted_tasks:
            category = _normalize_category(item.category)
            if item.due_at:
                due_at, _ = _parse_due_at(item.due_at)
                deadline_source = DeadlineSource.EXPLICIT
            else:
                due_at = last_message_at + timedelta(days=7)
                deadline_source = DeadlineSource.FALLBACK_7D
            extracted_tasks.append(
                ExtractedTask(
                    title=item.title.strip(),
                    category=category,
                    due_at=due_at,
                    deadline_source=deadline_source,
                    source_message_id=item.source_message_id,
                )
            )

        action_states = payload.action_states or [ActionState.FYI]
        return ThreadAnalysis(
            summary=payload.summary.strip(),
            action_items=[
                item.strip() for item in payload.action_items if item.strip()
            ],
            deadlines=deadlines,
            extracted_tasks=extracted_tasks,
            requested_items=[
                item.strip() for item in payload.requested_items if item.strip()
            ],
            recommended_next_action=payload.recommended_next_action.strip(),
            action_states=action_states,
            analyzed_at=datetime.now(UTC),
        )

    def _sync_agent_tasks(
        self,
        *,
        user_id: str,
        linked_account_id: str,
        conversation: ConversationRecord,
        thread: ThreadDetail,
        analysis: ThreadAnalysis,
    ) -> None:
        for extracted_task in analysis.extracted_tasks:
            origin_key = self._origin_key(
                thread_id=thread.id,
                title=extracted_task.title,
                category=extracted_task.category,
                source_message_id=extracted_task.source_message_id,
            )
            existing = self.task_store.get_task_by_origin_key(user_id, origin_key)
            if existing is not None and existing.status != TaskStatus.OPEN:
                continue

            task = TaskItem(
                id=existing.id if existing is not None else new_id("task"),
                title=extracted_task.title,
                status=existing.status if existing is not None else TaskStatus.OPEN,
                due_at=extracted_task.due_at,
                linked_account_id=linked_account_id,
                conversation_id=conversation.id,
                thread_id=thread.id,
                category=extracted_task.category,
                origin=TaskOrigin.AGENT,
                origin_key=origin_key,
                deadline_source=extracted_task.deadline_source,
                created_at=(
                    existing.created_at if existing is not None else datetime.now(UTC)
                ),
                completed_at=existing.completed_at if existing is not None else None,
            )
            self.task_store.upsert_task(user_id, task)

    def _origin_key(
        self,
        *,
        thread_id: str,
        title: str,
        category: str | None,
        source_message_id: str | None,
    ) -> str:
        payload = "|".join(
            [
                thread_id,
                source_message_id or "",
                (category or "").strip().lower(),
                " ".join(title.strip().lower().split()),
            ]
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
