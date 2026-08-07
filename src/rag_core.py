"""
src/rag_core.py — shared RAG plumbing for every specialist agent.

One Chroma persist directory, one collection per agent (PROJECT_PLAN.md
decision D3): the PT agent reads only `pt_docs`, the trainer only
`trainer_docs`. Knowledge siloing per specialist is the core product thesis —
an agent cannot leak into another's expertise.

Flow (ported from the opim-5517 reference architecture, simplified):
    load .pdf/.txt/.md → RecursiveCharacterTextSplitter(1000 / 150)
    → local MiniLM embeddings (no API key, no rate limits — decision D2)
    → Chroma collection → top-k similarity retrieval

The public contract of this module is frozen in PROJECT_PLAN.md §5.1 —
if you must change a signature, update the plan in the same PR.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import List

import chromadb
from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_community.document_loaders import TextLoader
try:
    from langchain_docling import DoclingLoader
except ImportError:
    DoclingLoader = None
from langchain_text_splitters import RecursiveCharacterTextSplitter

load_dotenv()

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

# Anchored to the repo root (not the process cwd) so ingest, the orchestrator
# CLI, and Streamlit all hit the same store no matter where they are launched.
_REPO_ROOT = Path(__file__).resolve().parent.parent
CHROMA_PERSIST_DIR = str(_REPO_ROOT / "chroma_db")

EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
# Migrated 2026-08-07 off `llama-3.3-70b-versatile`, which Groq retires on
# 2026-08-16 (D27). gpt-oss-120b is Groq's own recommended replacement and,
# unlike the model it replaces, supports tool calling -- which is what makes
# the specialist tool loop in agents/base.py possible at all.
#
# Operational note: gpt-oss models emit reasoning tokens before content, so
# they cost more per call than the model they replace. Anything that sets
# max_tokens must leave headroom or `content` comes back empty. Classification
# work should pass reasoning_effort="low" (measured: 43 vs 278 completion
# tokens for an identical answer) -- see GROQ_SMALL_MODEL below.
GROQ_MODEL = "openai/gpt-oss-120b"

# Small, cheap model for classification/planning: routing and agent selection.
# Also a `llama-3.1-8b-instant` replacement -- that one is retired 2026-08-16 too.
GROQ_SMALL_MODEL = "openai/gpt-oss-20b"

_SUPPORTED_EXTS = {".pdf", ".txt", ".md"}


# ─────────────────────────────────────────────────────────────────────────────
# Embeddings & LLM (cached singletons)
# ─────────────────────────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def _get_embeddings():
    """Local sentence-transformers embeddings — free, offline, no rate limits.

    First call downloads the model (~90 MB) to the HuggingFace cache; after
    that it loads from disk. Imported lazily so retrieval-free code paths
    (e.g. the router's rules pass) never pay the torch import cost.
    """
    from langchain_huggingface import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings(model_name=EMBED_MODEL)


@lru_cache(maxsize=1)
def _require_key() -> str:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "GROQ_API_KEY not found. Copy .env.example to .env and paste your "
            "free key from https://console.groq.com (see PROJECT_PLAN.md section 0)."
        )
    return api_key


@lru_cache(maxsize=1)
def get_llm():
    """Cached ChatGroq client shared by every agent and the synthesizer."""
    from langchain_groq import ChatGroq

    return ChatGroq(model=GROQ_MODEL, temperature=0.2, groq_api_key=_require_key())


@lru_cache(maxsize=1)
def get_small_llm():
    """Cached small-model client for classification and planning.

    `reasoning_effort="low"` matters here: gpt-oss spends completion tokens on
    reasoning before content, and for a routing decision the extra deliberation
    buys nothing (measured: 43 vs 278 completion tokens, same answer). On a
    free tier whose daily cap this project has hit repeatedly, that is the
    difference between a full test battery fitting in budget and not.
    """
    from langchain_groq import ChatGroq

    # `reasoning_effort` is a first-class ChatGroq parameter -- passing it via
    # model_kwargs raises a pydantic ValidationError at construction time.
    return ChatGroq(
        model=GROQ_SMALL_MODEL,
        temperature=0,
        groq_api_key=_require_key(),
        reasoning_effort="low",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Ingestion: load → chunk → embed → persist
# ─────────────────────────────────────────────────────────────────────────────


def load_folder_documents(folder: str) -> list:
    """Load every supported file (.pdf / .txt / .md) in a folder.

    Returns a flat list of LangChain Documents; each keeps the originating
    file path in ``metadata["source"]``, which becomes the citation label.
    """
    folder_path = Path(folder)
    if not folder_path.is_dir():
        raise FileNotFoundError(f"Corpus folder not found: {folder}")

    all_docs = []
    for path in sorted(folder_path.rglob("*")):
        if not path.is_file():
            continue
        ext = path.suffix.lower()
        if ext not in _SUPPORTED_EXTS:
            if path.name != ".gitkeep":
                print(f"[rag_core] Skipping unsupported file: {path.name}")
            continue
        if ext == ".pdf":
            if DoclingLoader is not None:
                loader = DoclingLoader(file_path=str(path))
            else:
                from langchain_community.document_loaders import PyPDFLoader
                loader = PyPDFLoader(str(path))
        else:
            loader = TextLoader(str(path), encoding="utf-8")
        docs = loader.load()
        all_docs.extend(docs)
        print(f"[rag_core] Loaded {len(docs)} document(s) from {path.name}")
    return all_docs


def split_documents(documents: list) -> list:
    """Chunk documents for embedding (same splitter settings as opim-5517)."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=150,
        length_function=len,
        add_start_index=True,
    )
    chunks = splitter.split_documents(documents)
    print(f"[rag_core] Split into {len(chunks)} chunk(s).")
    return chunks


def ingest_folder(folder: str, collection_name: str) -> int:
    """Load, chunk, embed, and persist a corpus folder into one collection.

    Re-running ADDS to the existing collection; call clear_collection()
    first (or ``python -m src.ingest --fresh``) for a clean rebuild.
    Returns the number of chunks added.
    """
    docs = load_folder_documents(folder)
    if not docs:
        print(f"[rag_core] No documents found in {folder}; nothing to ingest.")
        return 0

    chunks = split_documents(docs)
    
    # ChromaDB rejects nested dictionaries in metadata (which DocLing generates).
    # We must filter/flatten the complex metadata into primitives before inserting.
    from langchain_community.vectorstores.utils import filter_complex_metadata
    chunks = filter_complex_metadata(chunks)

    embeddings = _get_embeddings()

    # Chroma caps how many records one call may add; batching keeps us safe
    # for arbitrarily large corpora. Local embeddings need no sleep/throttle.
    BATCH = 1000
    vector_store = Chroma(
        persist_directory=CHROMA_PERSIST_DIR,
        collection_name=collection_name,
        embedding_function=embeddings,
    )
    for i in range(0, len(chunks), BATCH):
        vector_store.add_documents(chunks[i : i + BATCH])
        # Console prints stay ASCII-only: Windows terminals default to cp1252,
        # which crashes on fancy arrows/ellipses.
        print(f"[rag_core] Embedded {min(i + BATCH, len(chunks))}/{len(chunks)} chunks...")

    print(f"[rag_core] Collection '{collection_name}' updated -> {CHROMA_PERSIST_DIR}")
    return len(chunks)


def clear_collection(collection_name: str) -> None:
    """Delete one agent's collection (others are untouched — decision D3)."""
    if not Path(CHROMA_PERSIST_DIR).exists():
        print("[rag_core] No vector store on disk; nothing to clear.")
        return
    client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
    try:
        client.delete_collection(collection_name)
        print(f"[rag_core] Cleared collection '{collection_name}'.")
    except Exception:
        print(f"[rag_core] Collection '{collection_name}' does not exist; nothing to clear.")


# ─────────────────────────────────────────────────────────────────────────────
# Retrieval
# ─────────────────────────────────────────────────────────────────────────────


def _collection_count(collection_name: str) -> int:
    """How many chunks a collection holds; 0 if it has never been built."""
    if not Path(CHROMA_PERSIST_DIR).exists():
        return 0
    client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
    try:
        return client.get_collection(collection_name).count()
    except Exception:
        return 0


def retrieve(question: str, collection_name: str, k: int = 4) -> List:
    """Top-k similarity search over one agent's collection.

    Returns list[Document]. Raises FileNotFoundError with a fix-it message if
    the collection has never been built (the agent base class converts that
    into an ``error`` field so the orchestrator graph never crashes).
    """
    if _collection_count(collection_name) == 0:
        # Derived from ingest.py's AGENT_CORPORA rather than a second hardcoded
        # map -- the previous copy went stale when the surgeon and nutrition
        # collections were added, so their errors said "--agent <agent>".
        # Imported lazily to avoid a circular import at module load.
        try:
            from src.ingest import AGENT_CORPORA

            agent_flag = next(
                (flag for flag, (_, coll) in AGENT_CORPORA.items() if coll == collection_name),
                "<agent>",
            )
        except Exception:
            agent_flag = "<agent>"
        raise FileNotFoundError(
            f"Knowledge base '{collection_name}' has not been built yet. "
            f"Run: python -m src.ingest --agent {agent_flag}"
        )

    vector_store = Chroma(
        persist_directory=CHROMA_PERSIST_DIR,
        collection_name=collection_name,
        embedding_function=_get_embeddings(),
    )
    retriever = vector_store.as_retriever(
        search_type="similarity",
        search_kwargs={"k": k},
    )
    return retriever.invoke(question)
