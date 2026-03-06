from enum import StrEnum


class ActionState(StrEnum):
    TO_REPLY = "to_reply"
    TO_FOLLOW_UP = "to_follow_up"
    TASK = "task"
    FYI = "fyi"


class TaskStatus(StrEnum):
    OPEN = "open"
    COMPLETED = "completed"


class SyncStatus(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
