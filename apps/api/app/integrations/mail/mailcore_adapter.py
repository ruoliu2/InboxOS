from datetime import UTC, datetime, timedelta

from app.schemas.thread import ThreadDetail, ThreadMessage


class MailcoreAdapter:
    """Stub adapter that mimics Gmail sync output for MVP development."""

    def sync_threads(self, account_email: str | None = None) -> list[ThreadDetail]:
        now = datetime.now(UTC)
        account = account_email or "user@example.com"

        return [
            ThreadDetail(
                id="thr_1001",
                subject="Recruiter follow-up: personal information",
                snippet="Please send your updated resume and expected salary by Friday.",
                participants=["recruiter@acme.com", account],
                last_message_at=now - timedelta(hours=6),
                action_states=[],
                messages=[
                    ThreadMessage(
                        id="msg_1001_a",
                        sender="recruiter@acme.com",
                        sent_at=now - timedelta(hours=8),
                        body=(
                            "Hi, can you share your updated resume and expected salary "
                            "by 2026-03-07?"
                        ),
                    )
                ],
            ),
            ThreadDetail(
                id="thr_1002",
                subject="Customer onboarding checklist",
                snippet="Following up on API keys and SSO metadata.",
                participants=["ops@client.io", account],
                last_message_at=now - timedelta(days=1),
                action_states=[],
                messages=[
                    ThreadMessage(
                        id="msg_1002_a",
                        sender="ops@client.io",
                        sent_at=now - timedelta(days=2),
                        body=(
                            "Could you send over the API key rotation policy and SSO metadata? "
                            "Need this before March 10."
                        ),
                    ),
                    ThreadMessage(
                        id="msg_1002_b",
                        sender=account,
                        sent_at=now - timedelta(days=1, hours=12),
                        body="We will gather it and get back to you.",
                    ),
                ],
            ),
            ThreadDetail(
                id="thr_1003",
                subject="Weekly newsletter",
                snippet="Product news and release updates.",
                participants=["newsletter@vendor.com", account],
                last_message_at=now - timedelta(days=3),
                action_states=[],
                messages=[
                    ThreadMessage(
                        id="msg_1003_a",
                        sender="newsletter@vendor.com",
                        sent_at=now - timedelta(days=3),
                        body="Here are this week's updates from our product team.",
                    )
                ],
            ),
        ]
