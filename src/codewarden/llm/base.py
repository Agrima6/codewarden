from __future__ import annotations

import time
from typing import Protocol

import requests


class LLMError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class LLM(Protocol):
    def complete(self, system: str, user: str) -> str: ...


def _api_message(resp) -> str:
    """The provider's own error message if it sent JSON, else a short slice of the body."""
    try:
        err = resp.json().get("error", {})
        msg = err.get("message") if isinstance(err, dict) else None
        if msg:
            return msg.split(". For more information")[0][:200]
    except (ValueError, AttributeError, TypeError):
        pass
    return str(resp.text)[:200]


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
            last = f"HTTP {resp.status_code}: {_api_message(resp)}"
            if resp.status_code not in (408, 429, 500, 502, 503, 504):
                raise LLMError(last, resp.status_code)
        if attempt < retries:
            time.sleep(backoff * (2 ** attempt))
    raise LLMError(f"giving up after {retries + 1} attempts ({last})", status=503)
