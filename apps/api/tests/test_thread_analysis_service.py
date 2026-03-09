import json
from datetime import UTC, datetime

from app.core.config import get_settings
from app.schemas.common import ActionState, DeadlineSource, TaskStatus
from app.schemas.thread import ThreadDetail, ThreadMessage
from app.services.dependencies import (
    get_openai_compatible_client,
    get_task_store,
    get_thread_analysis_service,
)


def build_thread() -> ThreadDetail:
    return ThreadDetail(
        id="thread-1",
        subject="Quarterly update",
        snippet="Please send the revised deck next week.",
        participants=["founder@example.com", "user@example.com"],
        last_message_at=datetime(2026, 3, 8, 18, 0, tzinfo=UTC),
        action_states=[ActionState.TO_REPLY],
        messages=[
            ThreadMessage(
                id="msg-1",
                sender="founder@example.com",
                sent_at=datetime(2026, 3, 8, 18, 0, tzinfo=UTC),
                body=(
                    "Please send the revised deck by 2026-03-10 and follow up "
                    "on the contract next week."
                ),
            )
        ],
        analysis=None,
    )


def test_thread_analysis_service_applies_explicit_and_fallback_deadlines(
    monkeypatch,
):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    get_settings.cache_clear()
    get_openai_compatible_client.cache_clear()
    get_thread_analysis_service.cache_clear()
    service = get_thread_analysis_service()
    llm_client = get_openai_compatible_client()

    monkeypatch.setattr(
        llm_client,
        "create_chat_completion",
        lambda **_: json.dumps(
            {
                "summary": "Founder is asking for two deliverables.",
                "action_items": ["Send revised deck", "Follow up on contract"],
                "requested_items": ["Revised deck"],
                "recommended_next_action": (
                    "Reply with the deck timing and schedule the contract " "follow-up."
                ),
                "action_states": ["to_reply", "to_follow_up", "task"],
                "deadlines": [
                    {
                        "title": "Deck due",
                        "due_at": "2026-03-10",
                        "source_message_id": "msg-1",
                    }
                ],
                "extracted_tasks": [
                    {
                        "title": "Send revised deck",
                        "category": "deadline",
                        "due_at": "2026-03-10",
                        "source_message_id": "msg-1",
                    },
                    {
                        "title": "Follow up on contract",
                        "category": "follow_up",
                        "due_at": None,
                        "source_message_id": "msg-1",
                    },
                ],
            }
        ),
    )

    analyzed = service.analyze_thread(
        user_id="usr-1",
        linked_account_id="acct-1",
        provider="google_gmail",
        thread=build_thread(),
    )

    assert analyzed.analysis is not None
    assert analyzed.action_states == [
        ActionState.TO_REPLY,
        ActionState.TO_FOLLOW_UP,
        ActionState.TASK,
    ]
    assert analyzed.analysis.deadlines[0].is_date_only is True
    assert (
        analyzed.analysis.deadlines[0].due_at.isoformat() == "2026-03-10T17:00:00+00:00"
    )
    assert (
        analyzed.analysis.extracted_tasks[0].deadline_source == DeadlineSource.EXPLICIT
    )
    assert (
        analyzed.analysis.extracted_tasks[1].deadline_source
        == DeadlineSource.FALLBACK_7D
    )
    assert (
        analyzed.analysis.extracted_tasks[1].due_at.isoformat()
        == "2026-03-15T18:00:00+00:00"
    )


def test_thread_analysis_service_updates_open_agent_tasks_without_duplicates(
    monkeypatch,
):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    get_settings.cache_clear()
    get_openai_compatible_client.cache_clear()
    get_thread_analysis_service.cache_clear()
    service = get_thread_analysis_service()
    llm_client = get_openai_compatible_client()
    store = get_task_store()

    payload = {
        "summary": "One action item remains.",
        "action_items": ["Send revised deck"],
        "requested_items": [],
        "recommended_next_action": "Send the deck.",
        "action_states": ["task"],
        "deadlines": [],
        "extracted_tasks": [
            {
                "title": "Send revised deck",
                "category": "deadline",
                "due_at": "2026-03-10T12:00:00Z",
                "source_message_id": "msg-1",
            }
        ],
    }
    monkeypatch.setattr(
        llm_client,
        "create_chat_completion",
        lambda **_: json.dumps(payload),
    )

    thread = build_thread()
    service.analyze_thread(
        user_id="usr-1",
        linked_account_id="acct-1",
        provider="google_gmail",
        thread=thread,
    )
    tasks = store.list_tasks("usr-1")
    assert len(tasks) == 1
    assert tasks[0].status == TaskStatus.OPEN
    first_id = tasks[0].id

    payload["extracted_tasks"][0]["due_at"] = "2026-03-11T09:00:00Z"
    service.analyze_thread(
        user_id="usr-1",
        linked_account_id="acct-1",
        provider="google_gmail",
        thread=build_thread(),
    )
    tasks = store.list_tasks("usr-1")
    assert len(tasks) == 1
    assert tasks[0].id == first_id
    assert tasks[0].due_at.isoformat() == "2026-03-11T09:00:00+00:00"

    tasks[0].status = TaskStatus.COMPLETED
    tasks[0].completed_at = datetime(2026, 3, 9, 12, 0, tzinfo=UTC)
    store.upsert_task("usr-1", tasks[0])

    payload["extracted_tasks"][0]["due_at"] = "2026-03-12T09:00:00Z"
    service.analyze_thread(
        user_id="usr-1",
        linked_account_id="acct-1",
        provider="google_gmail",
        thread=build_thread(),
    )
    tasks = store.list_tasks("usr-1")
    assert len(tasks) == 1
    assert tasks[0].status == TaskStatus.COMPLETED
    assert tasks[0].due_at.isoformat() == "2026-03-11T09:00:00+00:00"
