from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "vendor", ".venv", "venv", "__pycache__", "dist", "build",
             ".next", "target", ".idea", ".chroma", ".pytest_cache"}


@dataclass(frozen=True)
class Chunk:
    path: str
    start: int  # 1-based inclusive
    end: int
    text: str


def iter_repo_files(root: Path, extensions: list[str], max_files: int, max_bytes: int):
    exts = {e.lower() for e in extensions}
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            if count >= max_files:
                return
            p = Path(dirpath) / name
            if p.suffix.lower() not in exts:
                continue
            try:
                if p.stat().st_size > max_bytes:
                    continue
                text = p.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            count += 1
            yield p.relative_to(root).as_posix(), text


def chunk_text(path: str, text: str, size: int = 40, overlap: int = 8) -> list[Chunk]:
    lines = text.splitlines()
    if not lines:
        return []
    step = max(1, size - overlap)
    chunks = []
    for start in range(0, len(lines), step):
        window = lines[start:start + size]
        body = "\n".join(window)
        if body.strip():
            chunks.append(Chunk(path, start + 1, start + len(window), body))
        if start + size >= len(lines):
            break
    return chunks


_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*")
_CAMEL = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")
_STOP = {"the", "and", "for", "not", "def", "return", "self", "var", "let", "const", "function",
         "class", "import", "from", "this", "that", "with", "true", "false", "none", "null"}


def tokenize(text: str) -> list[str]:
    """Split code into lowercase sub-words (snake_case and camelCase aware)."""
    out = []
    for word in _WORD.findall(text):
        parts = _CAMEL.findall(word)
        if len(parts) > 1:
            out.append(word.lower())
        out.extend(p.lower() for p in parts)
    return [t for t in out if len(t) > 2 and t not in _STOP]
