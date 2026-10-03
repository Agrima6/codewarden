from __future__ import annotations

from pathlib import PurePosixPath

from codewarden.rag.chunker import Chunk

_LANG_BY_EXT = {
    ".py": "PYTHON", ".js": "JS", ".jsx": "JS", ".ts": "TS", ".tsx": "TS", ".java": "JAVA", ".go": "GO",
    ".rb": "RUBY", ".rs": "RUST", ".c": "C", ".h": "C", ".cpp": "CPP", ".cs": "CSHARP", ".php": "PHP",
    ".kt": "KOTLIN", ".swift": "SWIFT", ".md": "MARKDOWN",
}


def _require():
    try:
        from langchain_text_splitters import Language, RecursiveCharacterTextSplitter
    except ImportError as exc:
        raise RuntimeError("rag.chunker=langchain needs: pip install 'codewarden[langchain]'") from exc
    return Language, RecursiveCharacterTextSplitter


def chunk_text_langchain(path: str, text: str, chunk_chars: int = 1600, overlap_chars: int = 160) -> list[Chunk]:
    """Split on code structure (classes, functions, blocks) instead of fixed line windows."""
    Language, Splitter = _require()
    lang = _LANG_BY_EXT.get(PurePosixPath(path).suffix.lower())
    if lang:
        splitter = Splitter.from_language(Language[lang], chunk_size=chunk_chars, chunk_overlap=overlap_chars,
                                          add_start_index=True)
    else:
        splitter = Splitter(chunk_size=chunk_chars, chunk_overlap=overlap_chars, add_start_index=True)
    chunks = []
    for doc in splitter.create_documents([text]):
        if not doc.page_content.strip():
            continue
        start = text.count("\n", 0, doc.metadata["start_index"]) + 1
        chunks.append(Chunk(path, start, start + doc.page_content.count("\n"), doc.page_content))
    return chunks


def as_langchain_retriever(retriever, k: int = 4):
    """Expose a CodeWarden retriever as a LangChain BaseRetriever so it can be used in LangChain chains."""
    try:
        from langchain_core.callbacks import CallbackManagerForRetrieverRun
        from langchain_core.documents import Document
        from langchain_core.retrievers import BaseRetriever
    except ImportError as exc:
        raise RuntimeError("needs: pip install 'codewarden[langchain]'") from exc

    class CodeWardenRetriever(BaseRetriever):
        top_k: int = k

        def _get_relevant_documents(self, query: str, *, run_manager: CallbackManagerForRetrieverRun):
            return [Document(page_content=c.text, metadata={"path": c.path, "start": c.start, "end": c.end})
                    for c in retriever.search(query, k=self.top_k)]

    return CodeWardenRetriever()
