from datetime import UTC, datetime

from app.integrations.llm.base import LLMAdapter
from app.schemas.common import ActionState
from app.schemas.thread import (
    ThreadAnalysis,
    ThreadDetail,
    ThreadMessage,
    ThreadSummary,
)
from app.services.id_factory import new_id
from app.storage.store import InMemoryStore


class ThreadService:
    def __init__(self, store: InMemoryStore, llm_adapter: LLMAdapter) -> None:
        self.store = store
        self.llm_adapter = llm_adapter

    def list_threads(
        self, action_state: ActionState | None = None
    ) -> list[ThreadSummary]:
        threads = list(self.store.threads.values())
        if action_state is not None:
            threads = [
                thread for thread in threads if action_state in thread.action_states
            ]

        threads.sort(key=lambda item: item.last_message_at, reverse=True)

        return [
            ThreadSummary(
                id=thread.id,
                subject=thread.subject,
                snippet=thread.snippet,
                participants=thread.participants,
                last_message_at=thread.last_message_at,
                action_states=thread.action_states,
            )
            for thread in threads
        ]

    def get_thread(self, thread_id: str) -> ThreadDetail:
        thread = self.store.threads.get(thread_id)
        if thread is None:
            raise KeyError(f"thread {thread_id} not found")
        return thread

    def analyze_thread(self, thread_id: str) -> tuple[ThreadDetail, ThreadAnalysis]:
        thread = self.get_thread(thread_id)
        analysis = self.llm_adapter.analyze_thread(thread)
        thread.analysis = analysis
        thread.action_states = analysis.action_states
        self.store.upsert_thread(thread)
        return thread, analysis

    def ensure_analyzed(self, thread: ThreadDetail) -> ThreadDetail:
        if thread.analysis is None:
            _, _ = self.analyze_thread(thread.id)
            thread = self.get_thread(thread.id)
        return thread

    def send_reply(
        self,
        thread_id: str,
        body: str,
        *,
        mute_thread: bool = False,
        sender: str = "you@example.com",
    ) -> tuple[ThreadDetail, ThreadMessage]:
        thread = self.get_thread(thread_id)
        normalized_body = body.strip()
        if not normalized_body:
            raise ValueError("Reply body must not be empty.")

        sent_at = datetime.now(UTC)
        sent_message = ThreadMessage(
            id=new_id("msg"),
            sender=sender,
            sent_at=sent_at,
            body=normalized_body,
        )
        thread.messages.append(sent_message)
        thread.snippet = normalized_body.replace("\n", " ")[:160]
        thread.last_message_at = sent_at
        if sender not in thread.participants:
            thread.participants.append(sender)

        thread.action_states = [ActionState.FYI]
        if thread.analysis is not None:
            thread.analysis.action_states = [ActionState.FYI]
            thread.analysis.recommended_next_action = (
                "Reply sent and thread muted."
                if mute_thread
                else "Reply sent. Monitor for follow-up."
            )
            thread.analysis.analyzed_at = sent_at

        self.store.upsert_thread(thread)
        return thread, sent_message
