"""Bind an index to the exact embedding model, including same-dimension upgrades."""
import json
import sqlite3


def identity() -> str:
    from app.config import EMBEDDING_DIM
    from app.embeddinggemma import MODEL_ID, REVISION, QUERY_PREFIX, DOCUMENT_PREFIX
    return json.dumps({"model": MODEL_ID, "revision": REVISION, "dimension": EMBEDDING_DIM,
                       "query_prefix": QUERY_PREFIX, "document_prefix": DOCUMENT_PREFIX},
                      sort_keys=True)


def require_compatible(conn: sqlite3.Connection) -> None:
    """Check without writing; an unmarked old index must be rebuilt separately."""
    try:
        row = conn.execute("SELECT identity FROM roms_embedding_space WHERE id=1").fetchone()
    except sqlite3.OperationalError as exc:
        raise ValueError("Embedding index has no model identity; set ROMS_DB_PATH to a new "
                         "database and re-ingest your documents with EmbeddingGemma 2") from exc
    if row is None or row[0] != identity():
        raise ValueError("Embedding index model identity differs; set ROMS_DB_PATH to a new "
                         "database and re-ingest your documents with EmbeddingGemma 2")


def initialize(conn: sqlite3.Connection) -> None:
    """Only stamp a fresh index. Never relabel pre-existing vectors."""
    existing = conn.execute("SELECT name FROM sqlite_master WHERE name IN "
                            "('vec_chunks', 'roms_embedding_space')").fetchone()
    if existing is not None:
        require_compatible(conn)
        return
    conn.execute("CREATE TABLE roms_embedding_space "
                 "(id INTEGER PRIMARY KEY CHECK(id=1), identity TEXT NOT NULL)")
    conn.execute("INSERT INTO roms_embedding_space VALUES (1, ?)", (identity(),))
