from __future__ import annotations

import os
import time

from codewarden.llm.base import LLMError, post_json

_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
REQUEST_TIMEOUT_S = 45
COOLDOWN_S = 180
CANDIDATES = ("gemini-3.6-flash", "gemini-3.5-flash", "gemini-3-flash-preview", "gemini-3.5-flash-lite",
              "gemini-flash-latest", "gemini-3.7-flash", "gemini-flash-lite-latest", "gemini-3.8-flash")
_cooldown: dict[str, float] = {}  # model -> time until which it is skipped after a failure


def pick_working_model(api_key: str, candidates: tuple[str, ...] = CANDIDATES, timeout: int = 25) -> str | None:
    """First candidate that answers a tiny request, so an experiment can pin one model for its whole run."""
    payload = {"contents": [{"role": "user", "parts": [{"text": "Reply with the single word ok."}]}],
               "generationConfig": {"maxOutputTokens": 16}}
    for model in candidates:
        try:
            post_json(_URL.format(model=model), payload, headers={"x-goog-api-key": api_key}, timeout=timeout, retries=0)
            return model
        except LLMError:
            continue
    return None


class GeminiLLM:
    def __init__(self, model: str, temperature: float = 0.2, api_key: str | None = None,
                 fallbacks: tuple[str, ...] = ()):
        self.model = model
        self.models = [model, *[m for m in fallbacks if m != model]]
        self.temperature = temperature
        self.usage = {"prompt": 0, "output": 0}
        self.models_used: set[str] = set()
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        if not self.api_key:
            raise LLMError("GEMINI_API_KEY is not set")

    def complete(self, system: str, user: str) -> str:
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": self.temperature,
                **({"responseMimeType": "application/json"} if "[task:qa]" not in system else {}),
                "maxOutputTokens": 4096,
            },
        }
        last: LLMError | None = None
        for attempt in range(2):  # a second pass rides out short demand spikes
            now = time.time()
            ready = [m for m in self.models if _cooldown.get(m, 0) <= now]
            for model in (ready or self.models):
                try:
                    data = post_json(_URL.format(model=model), payload, headers={"x-goog-api-key": self.api_key},
                                     timeout=REQUEST_TIMEOUT_S, retries=1 if len(self.models) > 1 else 3)
                    text = self._text(data)
                    meta = data.get("usageMetadata") or {}
                    self.usage["prompt"] += int(meta.get("promptTokenCount") or 0)
                    self.usage["output"] += int(meta.get("candidatesTokenCount") or 0) + int(meta.get("thoughtsTokenCount") or 0)
                    self.models_used.add(model)
                    return text
                except LLMError as exc:
                    last = exc
                    if exc.status not in (404, 429, 503):
                        raise
                    if len(self.models) > 1:
                        _cooldown[model] = time.time() + COOLDOWN_S
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
