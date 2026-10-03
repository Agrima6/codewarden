from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from pathlib import Path

import yaml

from codewarden.models import SEVERITIES

DEFAULT_MODELS = {
    "gemini": "gemini-2.5-flash",
    "ollama": "qwen2.5-coder:7b",
    "rules": "",
}

DEFAULT_EXCLUDE = [
    "*.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "go.sum",
    "*.min.js", "*.min.css", "*.map", "*.svg", "*.png", "*.jpg", "*.jpeg", "*.gif", "*.ico",
    "*.pdf", "*.zip", "dist/*", "build/*", "node_modules/*", "vendor/*", ".venv/*",
]

DEFAULT_RAG_EXTENSIONS = [
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rb", ".rs", ".c", ".h", ".cpp",
    ".cs", ".php", ".kt", ".swift", ".sh", ".sql", ".yml", ".yaml", ".md",
]


@dataclass
class RagConfig:
    enabled: bool = True
    backend: str = "bm25"  # bm25 | chroma
    chunker: str = "lines"  # lines | langchain
    top_k: int = 4
    chunk_lines: int = 40
    overlap: int = 8
    max_files: int = 3000
    max_file_bytes: int = 200_000
    extensions: list[str] = field(default_factory=lambda: list(DEFAULT_RAG_EXTENSIONS))


@dataclass
class Config:
    provider: str = "gemini"  # gemini | ollama | rules
    model: str = ""
    temperature: float = 0.2
    exclude: list[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDE))
    min_severity: str = "low"
    min_confidence: float = 0.5
    max_comments: int = 25
    fail_on: str = "none"  # none | low | medium | high | critical
    max_files: int = 40
    max_chars_per_request: int = 12_000
    redact_secrets: bool = True
    rag: RagConfig = field(default_factory=RagConfig)

    def resolved_model(self) -> str:
        return self.model or DEFAULT_MODELS.get(self.provider, "")

    def validate(self) -> None:
        if self.min_severity not in SEVERITIES:
            raise ValueError(f"min_severity must be one of {SEVERITIES}")
        if self.fail_on != "none" and self.fail_on not in SEVERITIES:
            raise ValueError(f"fail_on must be 'none' or one of {SEVERITIES}")
        if not 0 <= self.min_confidence <= 1:
            raise ValueError("min_confidence must be between 0 and 1")
        if self.max_comments < 1 or self.max_chars_per_request < 500:
            raise ValueError("max_comments must be >= 1 and max_chars_per_request >= 500")
        if self.rag.backend not in ("bm25", "chroma"):
            raise ValueError("rag.backend must be 'bm25' or 'chroma'")
        if self.rag.chunker not in ("lines", "langchain"):
            raise ValueError("rag.chunker must be 'lines' or 'langchain'")

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
        cfg = cls()
        p = Path(path) if path else Path(".codewarden.yml")
        if p.exists():
            data = yaml.safe_load(p.read_text()) or {}
            if not isinstance(data, dict):
                raise ValueError(f"{p} must contain a YAML mapping")
            known = {f.name for f in fields(cls)}
            for key, value in data.items():
                if key == "rag" and isinstance(value, dict):
                    rag_known = {f.name for f in fields(RagConfig)}
                    for rk, rv in value.items():
                        if rk not in rag_known:
                            raise ValueError(f"Unknown rag option: {rk}")
                        setattr(cfg.rag, rk, rv)
                elif key == "exclude":
                    cfg.exclude += [str(p) for p in (value or [])]
                elif key in known and key != "rag":
                    setattr(cfg, key, value)
                else:
                    raise ValueError(f"Unknown config option: {key}")
        elif path:
            raise FileNotFoundError(path)
        if os.environ.get("CODEWARDEN_PROVIDER"):
            cfg.provider = os.environ["CODEWARDEN_PROVIDER"]
        if os.environ.get("CODEWARDEN_MODEL"):
            cfg.model = os.environ["CODEWARDEN_MODEL"]
        extra = os.environ.get("CODEWARDEN_EXCLUDE", "")
        cfg.exclude += [p.strip() for p in extra.split(",") if p.strip()]
        cfg.validate()
        return cfg
