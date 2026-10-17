"""Hierarchical Topic Modeling, Dynamic Taxonomy, and Topic-Routed RAG.

Solves topic-drift and cross-domain false positives in large knowledge bases:
- Automatic topic extraction and hierarchical taxonomy clustering (Parent -> Subtopics)
- Topic-routed semantic retrieval: pre-filters candidate subgraphs before vector similarity
- Exposes topic graphs and taxonomy navigation for local LLM agents
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from app.db import get_connection

# Common stopwords to exclude from automatic topic identification
_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "with", "by", "from",
    "is", "are", "was", "were", "be", "been", "being", "have", "has", "had", "do", "does", "did",
    "will", "would", "shall", "should", "may", "might", "can", "could", "must", "of", "it", "this",
    "that", "these", "those", "when", "where", "which", "who", "whom", "whose", "why", "how",
    "all", "any", "both", "each", "few", "more", "most", "other", "some", "such", "no", "nor", "not",
    "only", "own", "same", "so", "than", "too", "very", "table", "columns", "row", "document", "file"
}


def extract_keywords_as_topics(text: str, max_topics: int = 4) -> List[str]:
    """Lightweight rule-based keyphrase and topic extraction without heavy NLP libraries."""
    words = re.findall(r"\b[a-zA-Z]{3,}\b", text.lower())
    freq: Dict[str, int] = {}
    for w in words:
        if w not in _STOPWORDS:
            freq[w] = freq.get(w, 0) + 1

    sorted_topics = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    return [t[0] for t in sorted_topics[:max_topics]]


def register_topic(
    topic_id: str,
    label: str,
    parent_topic: Optional[str] = None,
    description: str = "",
    db_path: Path | str | None = None,
) -> None:
    """Registers or updates a topic node in the hierarchical taxonomy."""
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO topics (topic_id, parent_topic, label, description, chunk_count)
        VALUES (?, ?, ?, ?, 0)
        ON CONFLICT(topic_id) DO UPDATE SET
            parent_topic = excluded.parent_topic,
            label = excluded.label,
            description = excluded.description
        """,
        (topic_id.lower().strip(), parent_topic.lower().strip() if parent_topic else None, label, description),
    )
    conn.commit()


def tag_chunks_with_topics(
    chunks: List[tuple[int, str]],
    conn: Any,
    doc_type: str = "general",
    refresh_topic_ids: Optional[Set[str]] = None,
) -> Set[str]:
    """Tag chunks in batches without committing the caller's transaction."""
    topic_rows: Set[str] = set(refresh_topic_ids or ())
    links = []
    for chunk_id, text in chunks:
        topics = extract_keywords_as_topics(text)
        if doc_type and doc_type != "general":
            topics.insert(0, doc_type.lower())
        for raw_topic in topics:
            topic_id = raw_topic.lower().strip()
            if not topic_id:
                continue
            topic_rows.add(topic_id)
            links.append((chunk_id, topic_id))

    cur = conn.cursor()
    cur.executemany(
        "INSERT OR IGNORE INTO topics (topic_id, label, parent_topic, chunk_count) VALUES (?, ?, NULL, 0)",
        [(topic_id, topic_id.title()) for topic_id in topic_rows],
    )
    cur.executemany(
        "INSERT OR REPLACE INTO chunk_topics (chunk_id, topic_id, score) VALUES (?, ?, 1.0)",
        links,
    )
    if topic_rows:
        placeholders = ",".join("?" for _ in topic_rows)
        cur.execute(
            f"UPDATE topics SET chunk_count = "
            f"(SELECT count(*) FROM chunk_topics WHERE chunk_topics.topic_id = topics.topic_id) "
            f"WHERE topic_id IN ({placeholders})",
            tuple(topic_rows),
        )
    return topic_rows


def tag_chunk_with_topics(
    chunk_id: int,
    text: str,
    doc_type: str = "general",
    db_path: Path | str | None = None,
) -> List[str]:
    """Tag one chunk and commit it for standalone callers."""
    conn = get_connection(db_path)
    topics = tag_chunks_with_topics([(chunk_id, text)], conn, doc_type)
    conn.commit()
    return sorted(topics)


def list_topics(db_path: Path | str | None = None) -> List[Dict[str, Any]]:
    """Lists all registered topics, hierarchy parent, and chunk counts."""
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("""
    SELECT topic_id, parent_topic, label, description, chunk_count
    FROM topics
    ORDER BY chunk_count DESC, topic_id ASC
    """)
    rows = cur.fetchall()
    return [
        {
            "topic_id": r[0],
            "parent_topic": r[1],
            "label": r[2],
            "description": r[3],
            "chunk_count": r[4],
        }
        for r in rows
    ]


def detect_query_topics(query: str, db_path: Path | str | None = None) -> List[str]:
    """Matches query tokens against existing topics in the taxonomy."""
    query_tokens = set(re.findall(r"\b[a-zA-Z]{3,}\b", query.lower()))
    registered = list_topics(db_path=db_path)

    matched = []
    for t in registered:
        t_id = t["topic_id"]
        if t_id in query_tokens:
            matched.append(t_id)

    return matched


def search_by_topic(
    topic: str,
    query: str,
    limit: int = 3,
    db_path: Path | str | None = None,
) -> List[Dict[str, Any]]:
    """Compatibility wrapper using the same local engine with an exact topic filter."""
    from app.rag_engine import local_search
    return [{**hit, 'topic': topic} for hit in local_search(
        query, limit=limit, db_path=db_path, filters={'topic': topic.lower().strip()})]
