from __future__ import annotations

from typing import Any

import httpx

from app.core.config import Settings


class LLMError(RuntimeError):
    pass


class OpenAICompatibleClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def enabled(self) -> bool:
        return bool(self.settings.llm_api_key and self.settings.llm_model)

    def create_chat_completion(
        self,
        *,
        messages: list[dict[str, str]],
        response_format: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
    ) -> str:
        if not self.enabled:
            raise LLMError("LLM API credentials are not configured.")

        headers = {
            "Authorization": f"Bearer {self.settings.llm_api_key}",
            "Content-Type": "application/json",
        }
        if self.settings.llm_http_referer:
            headers["HTTP-Referer"] = self.settings.llm_http_referer
        if self.settings.llm_app_name:
            headers["X-Title"] = self.settings.llm_app_name

        payload: dict[str, Any] = {
            "model": self.settings.llm_model,
            "messages": messages,
        }
        if response_format is not None:
            payload["response_format"] = response_format

        timeout = timeout_seconds or self.settings.llm_timeout_seconds
        url = f"{self.settings.llm_base_url.rstrip('/')}/chat/completions"

        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise TimeoutError("LLM request timed out.") from exc
        except httpx.HTTPError as exc:
            detail = ""
            if exc.response is not None:
                detail = exc.response.text.strip()
            raise LLMError(detail or "LLM request failed.") from exc

        body = response.json()
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LLMError("LLM response did not include any choices.")
        message = choices[0].get("message", {})
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content
        raise LLMError("LLM response did not include message content.")
