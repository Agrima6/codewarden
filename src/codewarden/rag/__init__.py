from __future__ import annotations

from pathlib import Path
from typing import Protocol

from codewarden.config import RagConfig
from codewarden.rag.chunker import Chunk, chunk_text, iter_repo_files


class Retriever(Protocol):
    chunks: list[Chunk]

    def search(self, query: str, k: int = 4, exclude=None) -> list[Chunk]: ...


def build_retriever(root: str | Path, cfg: RagConfig) -> Retriever | None:
    if not cfg.enabled:
        return None
    chunks: list[Chunk] = []
    for path, text in iter_repo_files(Path(root), cfg.extensions, cfg.max_files, cfg.max_file_bytes):
        chunks.extend(chunk_text(path, text, cfg.chunk_lines, cfg.overlap))
    if not chunks:
        return None
    if cfg.backend == "chroma":
        from codewarden.rag.chroma import ChromaRetriever
        return ChromaRetriever(chunks)
    from codewarden.rag.bm25 import BM25Retriever
    return BM25Retriever(chunks)


__all__ = ["Chunk", "Retriever", "build_retriever"]
