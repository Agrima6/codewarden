from __future__ import annotations

import os

from codewarden.llm.base import LLMError, post_json

_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiLLM:
    def __init__(self, model: str, temperature: float = 0.2, api_key: str | None = None):
        self.model = model
        self.temperature = temperature
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        if not self.api_key:
            raise LLMError("GEMINI_API_KEY is not set")

    def complete(self, system: str, user: str) -> str:
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": self.temperature,
                "responseMimeType": "application/json",
                "maxOutputTokens": 4096,
            },
        }
        data = post_json(_URL.format(model=self.model), payload, headers={"x-goog-api-key": self.api_key})
        try:
            parts = data["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts)
        except (KeyError, IndexError, TypeError) as exc:
            reason = (data.get("promptFeedback") or {}).get("blockReason") or "empty response"
            raise LLMError(f"Gemini returned no content ({reason})") from exc
