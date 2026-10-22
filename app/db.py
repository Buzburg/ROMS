"""Database connection management, sqlite-vec + FTS5 hybrid search initialization, and schema migrations.

Optimized for local LLMs:
- Write-Ahead Logging (WAL) for concurrent reads/writes
- Embedded sqlite-vec for float32 vector similarity
- SQLite FTS5 (BM25 porter tokenizer) for exact lexical search
- Persistent query embedding cache for sub-millisecond repeated queries
- Operational indexing for zero-latency table scans
"""

import sqlite3
import sqlite_vec
from pathlib import Path
from app.config import DB_PATH, EMBEDDING_DIM


import threading

_THREAD_LOCAL = threading.local()


def _create_raw_connection(target_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(target_path), timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")  # High performance safe durability
    conn.execute("PRAGMA cache_size=-64000;")   # 64MB page cache in RAM for instant queries
    conn.execute("PRAGMA mmap_size=268435456;") # 256MB memory-mapped I/O for zero-copy chunk reads
    conn.execute("PRAGMA temp_store=MEMORY;")   # Keep temp tables and sorting in RAM
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


def get_connection(db_path: Path | str | None = None, reuse: bool = True) -> sqlite3.Connection:
    """Creates or reuses a pooled thread-local SQLite connection with WAL mode enabled and sqlite-vec loaded."""
    target_path = Path(db_path) if db_path is not None else DB_PATH
    if target_path != Path(":memory:"):
        key = f"conn_{target_path}"
        if reuse:
            existing = getattr(_THREAD_LOCAL, key, None)
            if existing is not None:
                try:
                    _ = existing.total_changes
                    return existing
                except sqlite3.ProgrammingError:
                    pass
        target_path.parent.mkdir(parents=True, exist_ok=True)
        new_conn = _create_raw_connection(target_path)
        if reuse:
            setattr(_THREAD_LOCAL, key, new_conn)
        return new_conn

    return _create_raw_connection(target_path)


def init_database(db_path: Path | str | None = None) -> None:
    """Initializes ROMS database schema: OKF registry, vector virtual table, FTS5 lexical index, and operational tables."""
    conn = get_connection(db_path)
    cur = conn.cursor()

    # Reject incompatible indexes before modifying their schema or contents.
    schema = cur.execute("SELECT sql FROM sqlite_master WHERE name = 'vec_chunks'").fetchone()
    if schema is not None:
        import re
        dimension = re.search(r"embedding\s+float\s*\[\s*(\d+)\s*\]", schema[0], re.I)
        if dimension is None or int(dimension.group(1)) != EMBEDDING_DIM:
            raise ValueError(
                "Embedding dimension differs from the existing index; set ROMS_DB_PATH "
                "to a new database and re-ingest your documents"
            )

    # 1. OKF Registry: Tracks ingested documents, metadata, and SHA-256 checksums
    cur.execute("""
    CREATE TABLE IF NOT EXISTS okf_registry (
        doc_id TEXT PRIMARY KEY,
        title TEXT,
        doc_type TEXT,
        source_path TEXT,
        checksum TEXT,
        last_indexed TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # 2. RAG Vector Storage: vec0 virtual table with auxiliary columns (+prefix)
    cur.execute(f"""
    CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(
        chunk_id INTEGER PRIMARY KEY,
        +doc_id TEXT,
        embedding float[{EMBEDDING_DIM}],
        +content TEXT
    )
    """)

    # 3. RAG Lexical Storage: SQLite FTS5 with Porter Stemmer for BM25 keyword matching
    cur.execute("""
    CREATE VIRTUAL TABLE IF NOT EXISTS fts_chunks USING fts5(
        chunk_id UNINDEXED,
        doc_id UNINDEXED,
        content,
        tokenize='porter unicode61'
    )
    """)

    # 4. Query Embedding Cache: Sub-millisecond vector lookup for repeated or common queries
    cur.execute("""
    CREATE TABLE IF NOT EXISTS embedding_cache (
        query_hash TEXT PRIMARY KEY,
        embedding_blob BLOB,
        last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # 5. Operational Table: Support tickets for MCP tool interactions
    cur.execute("""
    CREATE TABLE IF NOT EXISTS support_tickets (
        ticket_id TEXT PRIMARY KEY,
        customer_email TEXT,
        issue_summary TEXT,
        status TEXT DEFAULT 'OPEN',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # 6. Operational Performance Indexes
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tickets_status ON support_tickets(status);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tickets_email ON support_tickets(customer_email);")

    # 7. Tool Registry & Discovery (AnyTool Smart Tool RAG)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS tool_registry (
        tool_name TEXT PRIMARY KEY,
        category TEXT,
        description TEXT,
        parameters_json TEXT,
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # 8. Tool Execution Analytics & Self-Healing Reliability Stats
    cur.execute("""
    CREATE TABLE IF NOT EXISTS tool_stats (
        tool_name TEXT PRIMARY KEY,
        call_count INTEGER DEFAULT 0,
        success_count INTEGER DEFAULT 0,
        fail_count INTEGER DEFAULT 0,
        total_latency_ms REAL DEFAULT 0.0,
        last_latency_ms REAL DEFAULT 0.0,
        last_error TEXT DEFAULT '',
        last_called TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # 9. UpSkill Trajectory Recording for SOP Distillation
    cur.execute("""
    CREATE TABLE IF NOT EXISTS agent_trajectories (
        session_id TEXT PRIMARY KEY,
        goal TEXT,
        steps_json TEXT,
        success INTEGER DEFAULT 0,
        final_result TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # 10. Secondary indexes for fast scans
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tool_cat ON tool_registry(category);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_traj_success ON agent_trajectories(success);")

    # 11. Hierarchical Topic Taxonomy & Topic Routing
    cur.execute("""
    CREATE TABLE IF NOT EXISTS topics (
        topic_id TEXT PRIMARY KEY,
        parent_topic TEXT,
        label TEXT,
        description TEXT DEFAULT '',
        chunk_count INTEGER DEFAULT 0
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS chunk_topics (
        chunk_id INTEGER,
        topic_id TEXT,
        score REAL DEFAULT 1.0,
        PRIMARY KEY (chunk_id, topic_id)
    )
    """)

    cur.execute("CREATE INDEX IF NOT EXISTS idx_chunk_topics_tid ON chunk_topics(topic_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_topics_parent ON topics(parent_topic);")

    # Local lessons use the same database without changing existing records.
    from app.memory import SCHEMA as MEMORY_SCHEMA
    conn.executescript(MEMORY_SCHEMA)

    # 12. AutoKarpathy Evaluation & Optimization Loop
    cur.execute("""
    CREATE TABLE IF NOT EXISTS karpathy_evals (
        eval_id TEXT PRIMARY KEY,
        task_name TEXT,
        prompt TEXT,
        score REAL,
        feedback TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    from app.knowledge_skills import schema as skill_schema
    skill_schema(conn)

    conn.commit()
    conn.close()
