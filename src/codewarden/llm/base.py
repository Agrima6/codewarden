from __future__ import annotations

import time
from typing import Protocol

import requests


class LLMError(RuntimeError):
    pass


class LLM(Protocol):
    def complete(self, system: str, user: str) -> str: ...


def post_json(url: str, payload: dict, headers: dict | None = None, timeout: int = 120,
              retries: int = 3, backoff: float = 2.0) -> dict:
    """POST JSON, retrying transient failures (429/5xx/network) with exponential backoff."""
    last = ""
    for attempt in range(retries + 1):
        try:
            resp = requests.post(url, json=payload, headers=headers or {}, timeout=timeout)
        except requests.RequestException as exc:
            last = f"network error: {exc.__class__.__name__}"
        else:
            if resp.status_code == 200:
                try:
                    return resp.json()
                except ValueError as exc:
                    raise LLMError("provider returned non-JSON response") from exc
            last = f"HTTP {resp.status_code}: {resp.text[:200]}"
            if resp.status_code not in (408, 429, 500, 502, 503, 504):
                raise LLMError(last)
        if attempt < retries:
            time.sleep(backoff * (2 ** attempt))
    raise LLMError(f"giving up after {retries + 1} attempts ({last})")
