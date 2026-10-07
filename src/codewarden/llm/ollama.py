from __future__ import annotations

import os

from codewarden.llm.base import LLMError, post_json


class OllamaLLM:
    """Local models (Code Llama, StarCoder2, DeepSeek Coder, Qwen Coder...) via Ollama."""

    def __init__(self, model: str, temperature: float = 0.2, host: str | None = None):
        self.model = model
        self.temperature = temperature
        self.usage = {"prompt": 0, "output": 0}
        self.models_used: set[str] = set()
        self.host = (host or os.environ.get("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")

    def complete(self, system: str, user: str) -> str:
        payload = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "options": {"temperature": self.temperature},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        data = post_json(f"{self.host}/api/chat", payload, timeout=300, retries=1)
        self.usage["prompt"] += int(data.get("prompt_eval_count") or 0)
        self.usage["output"] += int(data.get("eval_count") or 0)
        self.models_used.add(self.model)
        try:
            return data["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise LLMError("Ollama returned no message content") from exc
