from __future__ import annotations

import os
import time

from codewarden.llm.base import LLMError, post_json

_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiLLM:
    def __init__(self, model: str, temperature: float = 0.2, api_key: str | None = None,
                 fallbacks: tuple[str, ...] = ()):
        self.model = model
        self.models = [model, *[m for m in fallbacks if m != model]]
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
        last: LLMError | None = None
        for attempt in range(2):  # a second pass rides out short demand spikes
            for model in self.models:
                try:
                    data = post_json(_URL.format(model=model), payload, headers={"x-goog-api-key": self.api_key},
                                     retries=1 if len(self.models) > 1 else 3)
                    return self._text(data)
                except LLMError as exc:
                    last = exc
                    if exc.status not in (404, 429, 503):
                        raise
            if attempt == 0 and last.status != 404 and len(self.models) > 1:
                time.sleep(4)
            else:
                break
        raise last

    @staticmethod
    def _text(data: dict) -> str:
        try:
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts)
        except (KeyError, IndexError, TypeError):
            text = ""
        if not text.strip():
            reason = (data.get("promptFeedback") or {}).get("blockReason") or \
                ((data.get("candidates") or [{}])[0].get("finishReason")) or "empty response"
            raise LLMError(f"Gemini returned no content ({reason})", status=503)
        return text
