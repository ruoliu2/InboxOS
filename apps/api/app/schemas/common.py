from enum import StrEnum


class ActionState(StrEnum):
    TO_REPLY = "to_reply"
    TO_FOLLOW_UP = "to_follow_up"
    TASK = "task"
    FYI = "fyi"


class TaskStatus(StrEnum):
    OPEN = "open"
    COMPLETED = "completed"


class TaskOrigin(StrEnum):
    MANUAL = "manual"
    AGENT = "agent"


class DeadlineSource(StrEnum):
    EXPLICIT = "explicit"
    FALLBACK_7D = "fallback_7d"
