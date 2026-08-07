"""Persistent AI vector store — sqlite chunks + embeddings cache.

The rework's semantic search previously re-embedded every text chunk on
every request. This module stores the chunks and their embeddings in
``<project>/ai_index.sqlite3`` so search becomes a single query-embedding
plus pure-Python cosine scan. No FAISS/torch dependency: vectors are stored
as packed float32 blobs, exactly like the in-memory cosine path.
"""

from __future__ import annotations

import logging
import sqlite3
import struct
from pathlib import Path

import httpx
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from qualcoder_api.persistence.repositories import SourceRepository
from qualcoder_api.services.ai_service import (
    SIMILARITY_THRESHOLD,
    _chunk_text,
    _cosine,
)

logger = logging.getLogger(__name__)

INDEX_FILE = "ai_index.sqlite3"
BATCH_SIZE = 50


def _connect(project_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(Path(project_path) / INDEX_FILE))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS meta (model TEXT NOT NULL, chunks_count INTEGER NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS chunks (chunk_id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "source_id INTEGER NOT NULL, source_name TEXT NOT NULL, text TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS embeddings (chunk_id INTEGER PRIMARY KEY, "
        "dim INTEGER NOT NULL, vector BLOB NOT NULL)"
    )
    return conn


def index_status(project_path: str) -> dict:
    """Model + chunk count for the stored index (empty dict when absent)."""
    try:
        conn = _connect(project_path)
        try:
            row = conn.execute("SELECT model, chunks_count FROM meta").fetchone()
            if row is None:
                return {"indexed": False, "model": "", "chunks": 0}
            return {"indexed": True, "model": row[0], "chunks": row[1]}
        finally:
            conn.close()
    except sqlite3.Error as err:  # pragma: no cover - defensive
        logger.debug("index_status: %s", err)
        return {"indexed": False, "model": "", "chunks": 0}


def delete_index(project_path: str) -> None:
    try:
        (Path(project_path) / INDEX_FILE).unlink(missing_ok=True)
    except OSError as err:  # pragma: no cover - defensive
        logger.debug("delete_index: %s", err)


def _pack(vector: list[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def _unpack(blob: bytes) -> list[float]:
    return list(struct.unpack(f"<{len(blob) // 4}f", blob))


async def _embed_batch(client: AsyncClient, ai: dict, texts: list[str]) -> list[list[float]]:
    api_base = ai["api_base"].rstrip("/")
    headers = {}
    api_key = (ai.get("api_key") or "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        if ai.get("provider") == "claude":
            headers["anthropic-version"] = "2023-06-01"
    payload = {"model": ai["model"], "input": texts}
    response = await client.post(f"{api_base}/embeddings", json=payload, headers=headers)
    response.raise_for_status()
    data = response.json()
    return [item.get("embedding") or [] for item in (data.get("data") or [])]


async def rebuild_index(
    session_factory: async_sessionmaker,
    project_path: str,
    ai: dict,
) -> dict:
    """Re-embed every text chunk into the persistent index.

    Raises ``AiUnavailable`` when the embedding backend is unreachable.
    """
    from qualcoder_api.services.ai_service import AiUnavailable

    async with session_factory() as session:
        sources = await SourceRepository(session).list_sources()
    chunks: list[dict] = []
    for source in sources:
        fulltext = (source.fulltext or "").strip()
        if not fulltext:
            continue
        mediapath = source.mediapath or ""
        if mediapath and not mediapath.startswith(("/docs/", "docs:")):
            continue
        chunks.extend(_chunk_text(source, fulltext))
    if not chunks:
        delete_index(project_path)
        return {"indexed": True, "chunks": 0, "model": ai.get("model", "")}

    conn = _connect(project_path)
    try:
        conn.execute("DELETE FROM meta")
        conn.execute("DELETE FROM chunks")
        conn.execute("DELETE FROM embeddings")
        embedded = 0
        try:
            async with AsyncClient(timeout=120) as client:
                for start in range(0, len(chunks), BATCH_SIZE):
                    batch = chunks[start : start + BATCH_SIZE]
                    vectors = await _embed_batch(client, ai, [c["text"] for c in batch])
                    for chunk, vector in zip(batch, vectors, strict=False):
                        if not vector:
                            continue
                        cursor = conn.execute(
                            "INSERT INTO chunks (source_id, source_name, text) VALUES (?, ?, ?)",
                            (chunk["source_id"], chunk["file_name"], chunk["text"]),
                        )
                        conn.execute(
                            "INSERT INTO embeddings (chunk_id, dim, vector) VALUES (?, ?, ?)",
                            (cursor.lastrowid, len(vector), _pack(vector)),
                        )
                        embedded += 1
        except httpx.RequestError as err:
            raise AiUnavailable(
                f"AI backend unreachable at {ai['api_base']} — the /embeddings call failed."
            ) from err
        except httpx.HTTPStatusError as err:
            raise AiUnavailable(
                f"AI backend error {err.response.status_code} — embeddings may not be "
                "supported by this backend."
            ) from err
        conn.execute(
            "INSERT INTO meta (model, chunks_count) VALUES (?, ?)",
            (ai.get("model", ""), embedded),
        )
        conn.commit()
    finally:
        conn.close()
    return {"indexed": True, "chunks": embedded, "model": ai.get("model", "")}


async def search_index(
    project_path: str,
    ai: dict,
    query: str,
    limit: int = 10,
) -> list[dict]:
    """Semantic search against the stored index (single query embedding)."""
    from qualcoder_api.services.ai_service import AiUnavailable

    status = index_status(project_path)
    if not status["indexed"]:
        raise AiUnavailable(
            "No AI index yet — build it in the AI settings (Index documents)."
        )
    async with AsyncClient(timeout=60) as client:
        vectors = await _embed_batch(client, ai, [query])
    query_vector = vectors[0] if vectors else []
    if not query_vector:
        return []

    conn = _connect(project_path)
    try:
        rows = conn.execute(
            "SELECT c.source_id, c.source_name, c.text, e.vector FROM chunks c "
            "JOIN embeddings e ON e.chunk_id = c.chunk_id"
        ).fetchall()
    finally:
        conn.close()

    results = []
    for source_id, source_name, text_, blob in rows:
        vector = _unpack(blob)
        score = _cosine(query_vector, vector)
        if score >= SIMILARITY_THRESHOLD:
            results.append(
                {
                    "source_id": source_id,
                    "file_name": source_name,
                    "text": text_,
                    "score": round(score, 4),
                }
            )
    results.sort(key=lambda item: item["score"], reverse=True)
    return results[: max(0, limit)]
