"""Local RAG knowledge base helpers."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sarma_cli import paths
from sarma_cli.config import KnowledgeBaseConfig, RagConfig


TEXT_SUFFIXES = {
    ".bat",
    ".c",
    ".cfg",
    ".conf",
    ".cpp",
    ".css",
    ".go",
    ".h",
    ".hpp",
    ".htm",
    ".html",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".log",
    ".lua",
    ".md",
    ".markdown",
    ".php",
    ".ps1",
    ".py",
    ".rs",
    ".sh",
    ".sql",
    ".toml",
    ".ts",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}


@dataclass(slots=True)
class ChunkResult:
    files: int
    chunks: int
    output_path: Path


@dataclass(slots=True)
class PullResult:
    model: str
    path: Path


@dataclass(slots=True)
class ChunkDatabaseInfo:
    path: Path
    records: int


def upsert_knowledge_base(
    knowledge_bases: list[KnowledgeBaseConfig],
    knowledge_base: KnowledgeBaseConfig,
) -> None:
    for index, existing in enumerate(knowledge_bases):
        if existing.name == knowledge_base.name:
            knowledge_bases[index] = knowledge_base
            return
    knowledge_bases.append(knowledge_base)


def chunk_knowledge_base(kb: KnowledgeBaseConfig, rag: RagConfig) -> ChunkResult:
    root = knowledge_base_docs_path(kb)
    if not root.exists():
        raise FileNotFoundError(
            "Knowledge base docs directory does not exist. "
            f"Put files under: {root}"
        )

    files = list(_iter_text_files(root))
    output_path = knowledge_base_chroma_path(kb)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        shutil.rmtree(output_path)

    documents = []
    for file_path in files:
        text = _read_text(file_path)
        if not text.strip():
            continue
        for index, chunk in enumerate(_split_text(text, rag.chunk_size, rag.chunk_overlap)):
            documents.append({
                "text": chunk,
                "metadata": {
                    "knowledge_base": kb.name,
                    "embedding_model": rag.embedding_model,
                    "source": str(file_path),
                    "chunk_index": index,
                },
            })

    if documents:
        _write_chroma_documents(kb, rag, documents, output_path)

    return ChunkResult(files=len(files), chunks=len(documents), output_path=output_path)


def build_embedding_model(rag: RagConfig) -> Any:
    """Build the configured embedding model lazily.

    Current chunk search is lexical, but this provides the concrete boundary
    for future vectorization without coupling RAG to chat model providers.
    """
    backend = rag.embedding_backend.strip().lower() or "huggingface"
    model_name = _embedding_model_name(rag)
    if not model_name:
        raise ValueError("RAG embedding model is not configured.")

    if backend == "api":
        from langchain_openai import OpenAIEmbeddings

        kwargs: dict[str, Any] = {"model": rag.embedding_model}
        if rag.embedding_api_key:
            kwargs["api_key"] = rag.embedding_api_key
        if rag.embedding_api_base:
            kwargs["base_url"] = rag.embedding_api_base
        return OpenAIEmbeddings(**kwargs)

    if backend == "huggingface":
        from langchain_huggingface import HuggingFaceEmbeddings

        return HuggingFaceEmbeddings(model_name=model_name)

    raise ValueError(f"Unsupported RAG embedding backend: {rag.embedding_backend}")


def pull_embedding_model(rag: RagConfig) -> PullResult:
    """Pull a HuggingFace embedding model into the local RAG model cache."""
    backend = rag.embedding_backend.strip().lower() or "huggingface"
    if backend != "huggingface":
        raise ValueError("Only HuggingFace embedding models can be pulled locally.")
    if not rag.embedding_model.strip():
        raise ValueError("Set a HuggingFace embedding model id first.")

    target = embedding_model_local_path(rag)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RuntimeError(
            "Install langchain-huggingface to pull local embedding models."
        ) from exc

    path = snapshot_download(
        repo_id=rag.embedding_model.strip(),
        local_dir=str(target),
        local_dir_use_symlinks=False,
    )
    return PullResult(model=rag.embedding_model.strip(), path=Path(path))


def build_rag_search_tool(rag: RagConfig) -> Any:
    """Build the built-in LangChain RAG search tool."""
    from langchain_core.tools import tool

    @tool("rag_search")
    def rag_search(
        query: str,
        knowledge_base: str = "",
        top_k: int = 5,
    ) -> str:
        """Search chunked local RAG knowledge bases.

        Args:
            query: Search query.
            knowledge_base: Optional knowledge base name. Empty searches all
                enabled knowledge bases.
            top_k: Maximum number of matching chunks to return.
        """
        return search_knowledge_bases(
            rag,
            query=query,
            knowledge_base=knowledge_base,
            top_k=top_k,
        )

    return rag_search


def search_knowledge_bases(
    rag: RagConfig,
    *,
    query: str,
    knowledge_base: str = "",
    top_k: int = 5,
) -> str:
    query = query.strip()
    if not query:
        return "RAG search requires a non-empty query."

    requested = knowledge_base.strip()
    enabled = [kb for kb in rag.knowledge_bases if kb.enabled and kb.name]
    if requested:
        enabled = [kb for kb in enabled if kb.name == requested]
    if not enabled:
        return "No enabled RAG knowledge bases matched the request."

    results: list[tuple[str, dict[str, Any], float | None]] = []
    for kb in enabled:
        chroma_path = knowledge_base_chroma_path(kb)
        if not is_chroma_database(chroma_path):
            continue
        results.extend(_search_chroma_database(kb, rag, query, top_k))
    if not results:
        return "No RAG Chroma database results found. Open /rag and run Chunk KB first."

    top = results[: max(1, min(int(top_k or 5), 10))]
    parts = ["RAG search results:"]
    for index, (text, metadata, score) in enumerate(top, start=1):
        source = str(metadata.get("source") or "unknown")
        kb_name = str(metadata.get("knowledge_base") or "")
        chunk_index = metadata.get("chunk_index", "?")
        score_text = "" if score is None else f" score={score}"
        parts.append(
            f"\n[{index}] knowledge_base={kb_name}{score_text} "
            f"source={source} chunk={chunk_index}\n{_snippet(text)}"
        )
    return "\n".join(parts)


def validate_chroma_database(path: Path) -> ChunkDatabaseInfo:
    """Validate a Chroma persistent directory."""
    if not path.is_dir():
        raise FileNotFoundError(f"Chroma database directory not found: {path}")
    if not is_chroma_database(path):
        raise ValueError(
            "Chroma database must be a persist directory containing chroma.sqlite3."
        )
    return ChunkDatabaseInfo(path=path, records=0)


def knowledge_base_docs_dir(name: str) -> Path:
    return paths.rag_docs_dir() / _safe_name(name)


def knowledge_base_docs_path(kb: KnowledgeBaseConfig) -> Path:
    if kb.docs_path.strip():
        return Path(kb.docs_path).expanduser()
    return knowledge_base_docs_dir(kb.name)


def knowledge_base_chroma_path(kb: KnowledgeBaseConfig) -> Path:
    if kb.chroma_path.strip():
        return Path(kb.chroma_path).expanduser()
    return paths.rag_chroma_dir() / _safe_name(kb.name)


def is_chroma_database(path: Path) -> bool:
    return path.is_dir() and (path / "chroma.sqlite3").is_file()


def embedding_model_local_path(rag: RagConfig) -> Path:
    if rag.embedding_local_path.strip():
        return Path(rag.embedding_local_path).expanduser()
    return paths.rag_models_dir() / _safe_name(rag.embedding_model)


def _embedding_model_name(rag: RagConfig) -> str:
    if rag.embedding_backend.strip().lower() == "huggingface":
        local_path = embedding_model_local_path(rag)
        if local_path.exists():
            return str(local_path)
    return rag.embedding_model.strip()


def _write_chroma_documents(
    kb: KnowledgeBaseConfig,
    rag: RagConfig,
    records: list[dict[str, Any]],
    persist_directory: Path,
) -> None:
    from langchain_core.documents import Document
    from langchain_chroma import Chroma

    documents = [
        Document(
            page_content=str(record["text"]),
            metadata=dict(record.get("metadata") or {}),
        )
        for record in records
    ]
    Chroma.from_documents(
        documents=documents,
        embedding=build_embedding_model(rag),
        collection_name=_safe_name(kb.name),
        persist_directory=str(persist_directory),
    )


def _search_chroma_database(
    kb: KnowledgeBaseConfig,
    rag: RagConfig,
    query: str,
    top_k: int,
) -> list[tuple[str, dict[str, Any], float | None]]:
    from langchain_chroma import Chroma

    store = Chroma(
        collection_name=_safe_name(kb.name),
        persist_directory=str(knowledge_base_chroma_path(kb)),
        embedding_function=build_embedding_model(rag),
    )
    results = store.similarity_search_with_score(
        query,
        k=max(1, min(int(top_k or 5), 10)),
    )
    return [
        (
            str(document.page_content),
            dict(document.metadata or {}),
            float(score) if score is not None else None,
        )
        for document, score in results
    ]


def _snippet(text: str, limit: int = 900) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def _iter_text_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root] if _is_text_file(root) else []
    return [
        path
        for path in sorted(root.rglob("*"))
        if path.is_file() and _is_text_file(path)
    ]


def _is_text_file(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")


def _split_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    step = max(1, chunk_size - overlap)
    while start < len(text):
        end = min(len(text), start + chunk_size)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start += step
    return chunks


def _safe_name(name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", name.strip()).strip("-")
    return safe or "knowledge-base"
