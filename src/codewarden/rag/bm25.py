from __future__ import annotations

import math
from collections import Counter

from codewarden.rag.chunker import Chunk, tokenize


class BM25Retriever:
    """In-memory BM25 over code chunks. No dependencies, no model download."""

    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75):
        self.chunks = chunks
        self.k1, self.b = k1, b
        self._tf = [Counter(tokenize(c.text)) for c in chunks]
        self._len = [sum(tf.values()) for tf in self._tf]
        self._avg = (sum(self._len) / len(chunks)) if chunks else 0.0
        df: Counter = Counter()
        for tf in self._tf:
            df.update(tf.keys())
        n = len(chunks)
        self._idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    def search(self, query: str, k: int = 4, exclude=None) -> list[Chunk]:
        q = Counter(tokenize(query))
        if not q or not self.chunks:
            return []
        scored = []
        for i, chunk in enumerate(self.chunks):
            if exclude and exclude(chunk):
                continue
            tf, norm = self._tf[i], self.k1 * (1 - self.b + self.b * self._len[i] / (self._avg or 1))
            score = sum(
                self._idf.get(t, 0.0) * tf[t] * (self.k1 + 1) / (tf[t] + norm)
                for t in q if t in tf
            )
            if score > 0:
                scored.append((score, i))
        scored.sort(key=lambda s: -s[0])
        return [self.chunks[i] for _, i in scored[:k]]
