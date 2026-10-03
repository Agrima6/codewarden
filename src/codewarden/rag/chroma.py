from __future__ import annotations

from codewarden.rag.chunker import Chunk


class ChromaRetriever:
    """Semantic retriever backed by ChromaDB (pip install 'codewarden[chroma]')."""

    def __init__(self, chunks: list[Chunk]):
        try:
            import chromadb
        except ImportError as exc:
            raise RuntimeError("rag.backend=chroma needs: pip install 'codewarden[chroma]'") from exc
        self.chunks = chunks
        self._col = chromadb.EphemeralClient().create_collection(
            "codewarden", get_or_create=True, metadata={"hnsw:space": "cosine"}
        )
        for i in range(0, len(chunks), 256):
            batch = chunks[i:i + 256]
            self._col.add(
                ids=[str(i + j) for j in range(len(batch))],
                documents=[c.text for c in batch],
                metadatas=[{"path": c.path, "start": c.start, "end": c.end} for c in batch],
            )

    def search(self, query: str, k: int = 4, exclude=None) -> list[Chunk]:
        if not self.chunks or not query.strip():
            return []
        res = self._col.query(query_texts=[query], n_results=min(len(self.chunks), k * 3 + 5))
        out = []
        for id_ in res["ids"][0]:
            chunk = self.chunks[int(id_)]
            if exclude and exclude(chunk):
                continue
            out.append(chunk)
            if len(out) >= k:
                break
        return out
