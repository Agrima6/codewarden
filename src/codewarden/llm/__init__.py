from __future__ import annotations

from codewarden.config import Config
from codewarden.llm.base import LLM, LLMError


def get_llm(cfg: Config) -> LLM:
    model = cfg.resolved_model()
    if cfg.provider == "gemini":
        from codewarden.llm.gemini import GeminiLLM
        # An explicitly chosen model is used as is; the default alias falls back when a model is busy or retired.
        fallbacks = () if cfg.model else ("gemini-3.6-flash", "gemini-3.5-flash", "gemini-3-flash-preview", "gemini-3.5-flash-lite")
        return GeminiLLM(model, cfg.temperature, fallbacks=fallbacks)
    if cfg.provider == "ollama":
        from codewarden.llm.ollama import OllamaLLM
        return OllamaLLM(model, cfg.temperature)
    if cfg.provider == "rules":
        from codewarden.llm.rules import RulesLLM
        return RulesLLM()
    raise LLMError(f"Unknown provider {cfg.provider!r} (expected gemini, ollama or rules)")


__all__ = ["LLM", "LLMError", "get_llm"]
