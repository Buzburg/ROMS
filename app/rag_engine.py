"""RAG Engine: High-performance Hybrid Search (sqlite-vec + SQLite FTS5) with Reciprocal Rank Fusion (RRF).

Optimized for local LLMs:
- Dual-path retrieval: Semantic vector search + BM25 keyword search
- Reciprocal Rank Fusion (RRF) for optimal precision on codes, IDs, and conceptual queries
- In-memory & SQLite persistent query embedding cache for sub-millisecond retrieval
- Strict character/token budgeting to prevent local LLM prompt prefill freezing
"""

import hashlib
import json
import numpy as np
from app import config
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from collections import OrderedDict

from app.config import (
    get_embedding_model,
    compute_embedding_vector,
    MAX_RAG_CONTEXT_CHARS,
    MAX_RAG_CONTEXT_TOKENS,
    MIN_RELEVANCE_SCORE,
)
from app.db import get_connection
from app.prompt_builder import (
    format_context_for_local_llm,
    compress_chunks,
    build_grounded_system_prompt,
)

# In-memory LRU cache for query embedding vectors (avoids model inference for hot queries)
_MEM_CACHE: OrderedDict[tuple, bytes] = OrderedDict()
_MEM_CACHE_MAX = 512

# In-memory LRU cache for full hybrid search results (sub-millisecond instant retrieval)
_RESULT_CACHE: OrderedDict[tuple, List[Dict[str, Any]]] = OrderedDict()
_RESULT_CACHE_MAX = 512


def clear_result_cache():
    """Clears in-memory search result cache when knowledge documents are updated."""
    _RESULT_CACHE.clear()
    from app.zgsearch import clear_search_cache
    clear_search_cache()


def _embedding_namespace() -> tuple:
    """Identify the embedding space; never reuse another provider's vectors."""
    from app.embeddinggemma import REVISION
    return ('query-v3', config.EMBEDDING_PROVIDER, config.EMBEDDING_MODEL_NAME,
            config.EMBEDDING_DIM, REVISION)


def _valid_embedding_blob(blob: Any) -> bool:
    return (isinstance(blob, bytes)
            and len(blob) == config.EMBEDDING_DIM * 4
            and bool(np.isfinite(np.frombuffer(blob, dtype=np.float32)).all()))


def _get_query_embedding(
    query: str,
    db_path: Path | str | None = None,
    conn: Optional[Any] = None,
) -> bytes:
    """Returns serialized float32 embedding bytes using 2-tier caching (RAM -> SQLite -> Model)."""
    norm_query = query.strip().lower()
    payload = json.dumps((_embedding_namespace(), norm_query), ensure_ascii=False)
    q_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    db_tag = str(Path(db_path or config.DB_PATH).resolve())
    memory_key = (db_tag, q_hash)
    use_memory = conn is None and str(db_path) != ':memory:'

    # Caller-owned connections can contain private/uncommitted cache entries.
    if use_memory and memory_key in _MEM_CACHE:
        _MEM_CACHE.move_to_end(memory_key)
        return _MEM_CACHE[memory_key]

    # Tier 2: Persistent SQLite cache
    active_conn = conn or get_connection(db_path)
    cur = active_conn.cursor()
    cur.execute("SELECT embedding_blob FROM embedding_cache WHERE query_hash = ?", (q_hash,))
    row = cur.fetchone()
    if row is not None and _valid_embedding_blob(row[0]):
        emb_bytes = row[0]
        if use_memory:
            _MEM_CACHE[memory_key] = emb_bytes
            if len(_MEM_CACHE) > _MEM_CACHE_MAX:
                _MEM_CACHE.popitem(last=False)
        return emb_bytes

    # Tier 3: Compute via CPU-isolated SentenceTransformer or pluggable provider
    vec_list = compute_embedding_vector(norm_query)
    vector = np.asarray(vec_list, dtype=np.float32)
    if vector.shape != (config.EMBEDDING_DIM,) or not np.isfinite(vector).all():
        raise ValueError(f'Expected {config.EMBEDDING_DIM} finite float32 embedding values')
    emb_bytes = vector.tobytes()

    # Keep caller-owned transactions private; a read must never commit their edits.
    caller_transaction = active_conn.in_transaction
    cur.execute(
        "INSERT OR REPLACE INTO embedding_cache (query_hash, embedding_blob) VALUES (?, ?)",
        (q_hash, emb_bytes),
    )
    if not caller_transaction:
        active_conn.commit()

    if use_memory:
        _MEM_CACHE[memory_key] = emb_bytes
        if len(_MEM_CACHE) > _MEM_CACHE_MAX:
            _MEM_CACHE.popitem(last=False)

    return emb_bytes


def _sanitize_fts_query(query: str) -> str:
    """Sanitizes user queries into safe FTS5 query tokens."""
    # Unicode words and quoted literals preserve international text and prevent
    # FTS keywords (AND/OR/NOT/NEAR) from becoming query operators.
    tokens = dict.fromkeys(re.findall(r"\w+", query.casefold()))
    return " OR ".join(f'"{token}"' for token in tokens)


def vector_search(
    query: str,
    limit: int = 5,
    db_path: Path | str | None = None,
    conn: Optional[Any] = None,
    *, chunk_ids: Optional[List[int]] = None,
) -> List[Dict[str, Any]]:
    """Performs semantic vector search using sqlite-vec."""
    if chunk_ids is not None and not chunk_ids:
        return []
    active_conn = conn or get_connection(db_path)
    query_bytes = _get_query_embedding(query, db_path=db_path, conn=active_conn)

    cur = active_conn.cursor()
    restriction = " AND chunk_id IN (SELECT value FROM json_each(?))" if chunk_ids is not None else ""
    params = [query_bytes]
    if chunk_ids is not None:
        params.append(json.dumps(chunk_ids))
    params.append(limit)
    cur.execute(
        f"""
    SELECT doc_id, content, distance, chunk_id
    FROM vec_chunks
    WHERE embedding MATCH ? {restriction}
    ORDER BY distance
    LIMIT ?
    """,
        params,
    )

    rows = cur.fetchall()
    return [
        {
            "chunk_id": chunk_id,
            "doc_id": doc_id,
            "content": content,
            "distance": float(distance),
        }
        for doc_id, content, distance, chunk_id in rows
    ]


def lexical_search(
    query: str,
    limit: int = 5,
    db_path: Path | str | None = None,
    conn: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """Performs BM25 keyword search using SQLite FTS5."""
    safe_query = _sanitize_fts_query(query)
    if not safe_query:
        return []

    active_conn = conn or get_connection(db_path)
    cur = active_conn.cursor()

    cur.execute(
            """
        SELECT chunk_id, doc_id, content, bm25(fts_chunks) AS score
        FROM fts_chunks
        WHERE fts_chunks MATCH ?
        ORDER BY score
        LIMIT ?
        """,
            (safe_query, limit),
        )
    rows = cur.fetchall()

    return [
        {
            "chunk_id": chunk_id,
            "doc_id": doc_id,
            "content": content,
            "bm25_score": float(score),
        }
        for chunk_id, doc_id, content, score in rows
    ]


def _database_change_token(connection: Any) -> tuple:
    """data_version detects OTHER writers; total_changes detects this writer.

    Versions are only comparable on the same connection, so retain its identity
    in the bounded result-cache key rather than reusing an integer object id.
    """
    return (connection, connection.total_changes,
            connection.execute('PRAGMA data_version').fetchone()[0])


def _chunk_identity(item: Dict[str, Any]) -> tuple:
    """Identify indexed evidence by source chunk; fall back for legacy callers."""
    chunk_id = item.get('chunk_id')
    if chunk_id is not None:
        return ('chunk', chunk_id)
    return ('content', item['doc_id'], item['content'])


def hybrid_search(
    query: str,
    limit: int = 3,
    db_path: Path | str | None = None,
    k_constant: int = 60,
    min_score: float = 0.0,
    conn: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """Legacy low-level RRF API; application callers use local_search."""
    norm_q = query.strip().lower()
    db_tag = str(db_path) if db_path is not None else "default"
    active_conn = conn or get_connection(db_path)
    # A transaction may expose private edits or an old read snapshot. Neither
    # belongs in the global cache, even when using the pooled connection.
    use_cache = conn is None and not active_conn.in_transaction
    change_token = _database_change_token(active_conn) if use_cache else None
    cache_key = (db_tag, change_token, _embedding_namespace(), norm_q,
                 limit, k_constant, min_score)

    # Check Tier 0 result cache for hot repeats
    if use_cache and cache_key in _RESULT_CACHE:
        _RESULT_CACHE.move_to_end(cache_key)
        return [dict(item) for item in _RESULT_CACHE[cache_key]]

    fetch_limit = limit * 2
    vec_results = vector_search(query, limit=fetch_limit, db_path=db_path, conn=active_conn)
    lex_results = lexical_search(query, limit=fetch_limit, db_path=db_path, conn=active_conn)

    # Tuples reuse passage strings instead of copying/hashing concatenated text
    # on every search, and cannot collide on a delimiter inside doc_id/content.
    fusion_scores: Dict[tuple, Dict[str, Any]] = {}

    # 1. Score Vector Rank
    for rank, item in enumerate(vec_results, start=1):
        key = _chunk_identity(item)
        rrf_val = 1.0 / (k_constant + rank)
        fusion_scores[key] = {
            **({'chunk_id': item['chunk_id']} if item.get('chunk_id') is not None else {}),
            "doc_id": item["doc_id"],
            "content": item["content"],
            "score": rrf_val,
            "vector_dist": item["distance"],
            "bm25_rank": None,
        }

    # 2. Score Lexical Rank
    for rank, item in enumerate(lex_results, start=1):
        key = _chunk_identity(item)
        rrf_val = 1.0 / (k_constant + rank)
        if key in fusion_scores:
            fusion_scores[key]["score"] += rrf_val
            fusion_scores[key]["bm25_rank"] = rank
        else:
            fusion_scores[key] = {
                **({'chunk_id': item['chunk_id']} if item.get('chunk_id') is not None else {}),
                "doc_id": item["doc_id"],
                "content": item["content"],
                "score": rrf_val,
                "vector_dist": None,
                "bm25_rank": rank,
            }

    # Sort descending by fused RRF score
    sorted_items = sorted(fusion_scores.values(), key=lambda x: x["score"], reverse=True)
    if min_score > 0.0:
        sorted_items = [it for it in sorted_items if it["score"] >= min_score]

    top_items = sorted_items[:limit]

    # Keep the cache's dictionaries independent of caller mutations.
    if (use_cache and not active_conn.in_transaction
            and _database_change_token(active_conn) == change_token):
        _RESULT_CACHE[cache_key] = [dict(item) for item in top_items]
        if len(_RESULT_CACHE) > _RESULT_CACHE_MAX:
            _RESULT_CACHE.popitem(last=False)

    return top_items


def format_search_results(
    results: List[Dict[str, Any]], max_chars: int = MAX_RAG_CONTEXT_CHARS
) -> str:
    """Formats retrieved chunks with token budget compression for local LLMs."""
    if not results:
        return "No relevant documentation found."

    formatted = []
    total_chars = 0

    for r in results:
        doc_id = r["doc_id"]
        content = r["content"].strip()
        score = r.get("score", 0.0)

        # Budget check to prevent freezing local LLM prompt prefill
        if total_chars + len(content) > max_chars:
            remaining = max_chars - total_chars
            if remaining > 80:
                truncated = content[:remaining] + "... [TRUNCATED FOR TOKEN BUDGET]"
                formatted.append(f"[Source: {doc_id} | Score: {score:.3f}]\n{truncated}")
            break

        formatted.append(f"[Source: {doc_id} | Score: {score:.3f}]\n{content}")
        total_chars += len(content)

    return "\n\n---\n\n".join(formatted)


def local_search(query: str, limit: int = 3, db_path: Path | str | None = None,
                 min_score: float = 0.0, *, filters=None) -> List[Dict[str, Any]]:
    """One adaptive local retrieval path for Python tools, chat and research."""
    from app.zgsearch import zg_search
    return [item for item in zg_search(query, limit=limit, db_path=db_path, filters=filters)
            if item['score'] >= min_score]


def search_knowledge_base(
    query: str, limit: int = 3, db_path: Path | str | None = None, *, filters=None
) -> str:
    """Unified entrypoint executing hybrid RRF search with context window budgeting."""
    results = local_search(query, limit=limit, db_path=db_path, filters=filters)
    return format_search_results(results)


def search_grounded_context(
    query: str,
    limit: int = 3,
    max_tokens: int = MAX_RAG_CONTEXT_TOKENS,
    db_path: Path | str | None = None,
    format_style: str = "xml",
) -> str:
    """Retrieves top chunks and formats them as a clean XML or Markdown context block for local LLMs."""
    results = local_search(query, limit=limit, db_path=db_path, min_score=MIN_RELEVANCE_SCORE)
    return format_context_for_local_llm(results, format_style=format_style, max_tokens=max_tokens)

