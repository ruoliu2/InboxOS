from app.schemas.common import ActionState
from app.schemas.thread import ThreadAnalysis, ThreadDetail


class ActionService:
    def apply_analysis(
        self, thread: ThreadDetail, analysis: ThreadAnalysis
    ) -> ThreadDetail:
        thread.analysis = analysis
        thread.action_states = self._unique_states(analysis.action_states)
        return thread

    def mark_replied(self, thread: ThreadDetail) -> ThreadDetail:
        thread.action_states = [
            state for state in thread.action_states if state != ActionState.TO_REPLY
        ]
        if not thread.action_states:
            thread.action_states = [ActionState.FYI]
        return thread

    def mark_followed_up(self, thread: ThreadDetail) -> ThreadDetail:
        thread.action_states = [
            state for state in thread.action_states if state != ActionState.TO_FOLLOW_UP
        ]
        if not thread.action_states:
            thread.action_states = [ActionState.FYI]
        return thread

    def _unique_states(self, states: list[ActionState]) -> list[ActionState]:
        seen: set[ActionState] = set()
        ordered: list[ActionState] = []

        for state in states:
            if state in seen:
                continue
            seen.add(state)
            ordered.append(state)

        return ordered or [ActionState.FYI]
