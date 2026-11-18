from unittest.mock import MagicMock

import pytest

from codewarden.config import Config
from codewarden.llm import LLMError, get_llm
from codewarden.llm.gemini import GeminiLLM
from codewarden.llm.ollama import OllamaLLM


def _ok(payload):
    return MagicMock(status_code=200, json=lambda: payload, text="")


def test_gemini_request_shape_and_response(monkeypatch):
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen.update(url=url, json=json, headers=headers)
        return _ok({"candidates": [{"content": {"parts": [{"text": '{"findings": '}, {"text": "[]}"}]}}]})

    monkeypatch.setattr("codewarden.llm.base.requests.post", fake_post)
    out = GeminiLLM("gemini-2.5-flash", 0.1, api_key="KEY").complete("SYS", "USER")
    assert out == '{"findings": []}'
    assert seen["url"].endswith("/models/gemini-2.5-flash:generateContent")
    assert seen["headers"] == {"x-goog-api-key": "KEY"}, "key must travel in a header, not the URL"
    assert "KEY" not in seen["url"]
    assert seen["json"]["systemInstruction"]["parts"][0]["text"] == "SYS"
    assert seen["json"]["contents"][0]["parts"][0]["text"] == "USER"
    assert seen["json"]["generationConfig"]["responseMimeType"] == "application/json"


def test_gemini_blocked_response_is_an_llm_error(monkeypatch):
    monkeypatch.setattr("codewarden.llm.base.requests.post",
                        lambda *a, **k: _ok({"promptFeedback": {"blockReason": "SAFETY"}}))
    with pytest.raises(LLMError, match="SAFETY"):
        GeminiLLM("m", api_key="k").complete("s", "u")


def test_gemini_requires_a_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(LLMError, match="GEMINI_API_KEY"):
        GeminiLLM("m")


def test_ollama_request_shape(monkeypatch):
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen.update(url=url, json=json)
        return _ok({"message": {"content": "hello"}})

    monkeypatch.setattr("codewarden.llm.base.requests.post", fake_post)
    assert OllamaLLM("qwen2.5-coder:7b", host="http://box:11434/").complete("S", "U") == "hello"
    assert seen["url"] == "http://box:11434/api/chat"
    assert seen["json"]["format"] == "json" and seen["json"]["stream"] is False
    assert [m["role"] for m in seen["json"]["messages"]] == ["system", "user"]


def test_provider_factory():
    cfg = Config()
    cfg.provider = "rules"
    assert get_llm(cfg).__class__.__name__ == "RulesLLM"
    cfg.provider = "nope"
    with pytest.raises(LLMError):
        get_llm(cfg)


def test_gemini_falls_back_when_a_model_is_busy_retired_or_empty(monkeypatch):
    tried = []

    def fake_post(url, json=None, headers=None, timeout=None):
        model = url.split("/models/")[1].split(":")[0]
        tried.append(model)
        if model == "a":
            return MagicMock(status_code=503, text="busy", json=lambda: {})
        if model == "b":
            return MagicMock(status_code=404, text="retired", json=lambda: {})
        if model == "c":
            return _ok({"candidates": [{"finishReason": "OTHER"}]})
        return _ok({"candidates": [{"content": {"parts": [{"text": "fine"}]}}]})

    monkeypatch.setattr("codewarden.llm.base.requests.post", fake_post)
    monkeypatch.setattr("codewarden.llm.base.time.sleep", lambda s: None)
    out = GeminiLLM("a", api_key="k", fallbacks=("b", "c", "d")).complete("s", "u")
    assert out == "fine" and [m for i, m in enumerate(tried) if i == 0 or tried[i - 1] != m] == ["a", "b", "c", "d"]


def test_gemini_does_not_fall_back_on_auth_errors(monkeypatch):
    calls = []
    monkeypatch.setattr("codewarden.llm.base.requests.post",
                        lambda url, **k: calls.append(1) or MagicMock(status_code=403, text="bad key"))
    with pytest.raises(LLMError):
        GeminiLLM("a", api_key="k", fallbacks=("b",)).complete("s", "u")
    assert len(calls) == 1


def test_qa_requests_are_plain_text_but_reviews_stay_json(monkeypatch):
    from codewarden.qa import QA_SYSTEM
    from codewarden.prompts import SYSTEM_PROMPT
    seen = []

    def fake_post(url, json=None, headers=None, timeout=None):
        seen.append(json)
        if "generateContent" in url:
            return _ok({"candidates": [{"content": {"parts": [{"text": "answer"}]}}]})
        return _ok({"message": {"content": "answer"}})

    monkeypatch.setattr("codewarden.llm.base.requests.post", fake_post)
    for llm in (GeminiLLM("m", api_key="k"), OllamaLLM("m")):
        seen.clear()
        llm.complete(QA_SYSTEM, "q")
        llm.complete(SYSTEM_PROMPT, "diff")
        qa, review = seen
        assert "format" not in qa and "responseMimeType" not in qa.get("generationConfig", {})
        assert review.get("format") == "json" or review["generationConfig"]["responseMimeType"] == "application/json"
