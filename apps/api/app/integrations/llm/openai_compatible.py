from __future__ import annotations

import re
from datetime import UTC, datetime

from app.schemas.common import ActionState
from app.schemas.thread import ThreadAnalysis, ThreadDetail

_DATE_PATTERNS = [
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(
        r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2}\b",
        re.IGNORECASE,
    ),
]

_REQUEST_PATTERNS = [
    re.compile(r"\b(can you|could you|please|need|share|send)\b", re.IGNORECASE),
    re.compile(r"\?$"),
]

_FOLLOWUP_PATTERNS = [
    re.compile(r"\bfollow up\b", re.IGNORECASE),
    re.compile(r"\bchecking in\b", re.IGNORECASE),
]


class OpenAICompatibleAdapter:
    """Heuristic adapter with an OpenAI-compatible surface for MVP."""

    def analyze_thread(self, thread: ThreadDetail) -> ThreadAnalysis:
        joined = "\n".join(message.body for message in thread.messages)
        summary = self._build_summary(thread, joined)
        action_items = self._extract_action_items(joined)
        deadlines = self._extract_deadlines(joined)
        requested_items = self._extract_requested_items(joined)
        action_states = self._derive_states(joined, action_items, deadlines)
        recommendation = self._recommend(action_states, requested_items)

        return ThreadAnalysis(
            summary=summary,
            action_items=action_items,
            deadlines=deadlines,
            requested_items=requested_items,
            recommended_next_action=recommendation,
            action_states=action_states,
            analyzed_at=datetime.now(UTC),
        )

    def _build_summary(self, thread: ThreadDetail, body: str) -> str:
        if "newsletter" in thread.subject.lower():
            return "FYI update with no clear action request."
        first_sentence = body.split(".")[0].strip()
        return first_sentence or thread.snippet

    def _extract_action_items(self, body: str) -> list[str]:
        items: list[str] = []
        normalized = body.lower()

        if "resume" in normalized:
            items.append("Send updated resume")
        if "salary" in normalized:
            items.append("Share expected salary")
        if "api key" in normalized:
            items.append("Provide API key rotation policy")
        if "sso" in normalized:
            items.append("Provide SSO metadata")

        if not items and any(pattern.search(body) for pattern in _REQUEST_PATTERNS):
            items.append("Reply with the requested information")

        return items

    def _extract_requested_items(self, body: str) -> list[str]:
        requests: list[str] = []
        lowered = body.lower()

        for candidate in [
            "updated resume",
            "expected salary",
            "api key rotation policy",
            "sso metadata",
        ]:
            if candidate in lowered:
                requests.append(candidate)

        return requests

    def _extract_deadlines(self, body: str) -> list[str]:
        results: list[str] = []
        for pattern in _DATE_PATTERNS:
            results.extend(match.group(0) for match in pattern.finditer(body))

        return sorted(set(results))

    def _derive_states(
        self,
        body: str,
        action_items: list[str],
        deadlines: list[str],
    ) -> list[ActionState]:
        states: list[ActionState] = []

        if any(pattern.search(body) for pattern in _REQUEST_PATTERNS) or action_items:
            states.append(ActionState.TO_REPLY)

        if any(pattern.search(body) for pattern in _FOLLOWUP_PATTERNS):
            states.append(ActionState.TO_FOLLOW_UP)

        if deadlines:
            states.append(ActionState.TASK)

        if not states:
            states.append(ActionState.FYI)

        return states

    def _recommend(self, states: list[ActionState], requested_items: list[str]) -> str:
        if ActionState.TO_REPLY in states:
            if requested_items:
                joined = ", ".join(requested_items)
                return f"Reply and include: {joined}."
            return "Reply with requested information."

        if ActionState.TASK in states:
            return "Create a reminder task for the deadline."

        return "Mark as FYI and archive when reviewed."
