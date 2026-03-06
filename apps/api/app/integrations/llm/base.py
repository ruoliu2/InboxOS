from typing import Protocol

from app.schemas.thread import ThreadAnalysis, ThreadDetail


class LLMAdapter(Protocol):
    def analyze_thread(self, thread: ThreadDetail) -> ThreadAnalysis: ...
