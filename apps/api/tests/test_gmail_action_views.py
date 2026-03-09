from datetime import UTC, datetime

from app.schemas.common import ActionState, DeadlineSource
from app.schemas.thread import ExtractedTask, ThreadDetail, ThreadMessage
from app.services.dependencies import (
    get_auth_store,
    get_conversation_store,
    get_google_workspace_client,
)
from app.storage.conversation_store import (
    ConversationInsightRecord,
    new_conversation_record,
)
from tests.conftest import build_session


def seed_conversation() -> None:
    store = get_conversation_store()
    conversation = store.upsert_conversation(
        new_conversation_record(
            user_id="usr-1",
            linked_account_id="acct-1",
            provider="google_gmail",
            external_conversation_id="thread-1",
            title="Launch checklist",
            preview="Please reply with the revised launch deck.",
            last_message_at=datetime(2026, 3, 8, 18, 0, tzinfo=UTC),
            source_folder="inbox",
        )
    )
    conversation.metadata = {
        "participants": ["founder@example.com", "user@example.com"],
    }
    conversation = store.upsert_conversation(conversation)
    store.upsert_insight(
        ConversationInsightRecord(
            conversation_id=conversation.id,
            summary="Founder needs a reply and a follow-up task.",
            action_items=["Send launch deck"],
            deadlines=[],
            extracted_tasks=[
                ExtractedTask(
                    title="Send launch deck",
                    category="reply",
                    due_at=datetime(2026, 3, 15, 18, 0, tzinfo=UTC),
                    deadline_source=DeadlineSource.FALLBACK_7D,
                    source_message_id="msg-1",
                )
            ],
            requested_items=["Launch deck"],
            recommended_next_action="Reply with the revised launch deck.",
            action_states=[ActionState.TO_REPLY.value, ActionState.TO_FOLLOW_UP.value],
            analyzed_at=datetime(2026, 3, 8, 18, 5, tzinfo=UTC),
            created_at=datetime(2026, 3, 8, 18, 5, tzinfo=UTC),
            updated_at=datetime(2026, 3, 8, 18, 5, tzinfo=UTC),
        )
    )


def test_gmail_action_views_and_counts_use_persisted_insights(client, monkeypatch):
    session = build_session(user_id="usr-1", active_linked_account_id="acct-1")
    get_auth_store().upsert_session(session)
    client.cookies.set("inboxos_session", session.session_id, domain="testserver.local")
    seed_conversation()

    google_client = get_google_workspace_client()
    monkeypatch.setattr(
        google_client,
        "list_gmail_threads",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("action views should not call Gmail list")
        ),
    )

    threads_response = client.get("/gmail/threads?action_state=to_reply")
    assert threads_response.status_code == 200
    assert threads_response.json()["threads"][0]["id"] == "thread-1"
    assert threads_response.json()["threads"][0]["action_states"] == [
        "to_reply",
        "to_follow_up",
    ]

    counts_response = client.get("/gmail/action-counts")
    assert counts_response.status_code == 200
    assert counts_response.json() == {"to_reply": 1, "to_follow_up": 1}


def test_gmail_thread_route_hydrates_persisted_analysis(client, monkeypatch):
    session = build_session(user_id="usr-1", active_linked_account_id="acct-1")
    get_auth_store().upsert_session(session)
    client.cookies.set("inboxos_session", session.session_id, domain="testserver.local")
    seed_conversation()

    google_client = get_google_workspace_client()
    monkeypatch.setattr(
        google_client,
        "get_gmail_thread",
        lambda access_token, thread_id: ThreadDetail(
            id=thread_id,
            subject="Launch checklist",
            snippet="Please reply with the revised launch deck.",
            participants=["founder@example.com", "user@example.com"],
            last_message_at=datetime(2026, 3, 8, 18, 0, tzinfo=UTC),
            action_states=[ActionState.FYI],
            messages=[
                ThreadMessage(
                    id="msg-1",
                    sender="founder@example.com",
                    sent_at=datetime(2026, 3, 8, 18, 0, tzinfo=UTC),
                    body="Please reply with the revised launch deck.",
                )
            ],
            analysis=None,
        ),
    )

    response = client.get("/gmail/threads/thread-1")
    assert response.status_code == 200
    payload = response.json()
    assert payload["action_states"] == ["to_reply", "to_follow_up"]
    assert (
        payload["analysis"]["summary"] == "Founder needs a reply and a follow-up task."
    )
    assert payload["analysis"]["extracted_tasks"][0]["deadline_source"] == "fallback_7d"
