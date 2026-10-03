from __future__ import annotations

from codewarden.config import Config
from codewarden.llm.base import LLM, LLMError


def get_llm(cfg: Config) -> LLM:
    model = cfg.resolved_model()
    if cfg.provider == "gemini":
        from codewarden.llm.gemini import GeminiLLM
        return GeminiLLM(model, cfg.temperature)
    if cfg.provider == "ollama":
        from codewarden.llm.ollama import OllamaLLM
        return OllamaLLM(model, cfg.temperature)
    if cfg.provider == "rules":
        from codewarden.llm.rules import RulesLLM
        return RulesLLM()
    raise LLMError(f"Unknown provider {cfg.provider!r} (expected gemini, ollama or rules)")


__all__ = ["LLM", "LLMError", "get_llm"]
