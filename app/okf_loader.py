"""OKF (Open Knowledge Format) & Universal Multi-Format Document Ingestion Engine.

Document intake capabilities:
- Heterogeneous document support: .md, .csv, .json/.jsonl, .txt, source code (.py, .mojo, .sql, .ts, etc.)
- Schema-preserving tabular chunking: Column headers retained across every CSV chunk
- Synchronously populates both sqlite-vec (semantic vector index) and SQLite FTS5 (BM25 lexical index)
- SHA-256 deduplication and Tier-0 RRF cache auto-invalidation
"""

import hashlib
import json
import os
from pathlib import Path
from typing import List, Optional, Tuple
import numpy as np

from app.config import get_embedding_model, KNOWLEDGE_DIR
from app.db import get_connection
from app.document_extract import BINARY_EXTENSIONS
from app.document_parse import parse_document, fit_model_window, PARSER_VERSION

SUPPORTED_EXTENSIONS = {
    ".md",
    ".markdown",
    ".csv",
    ".tsv",
    ".json",
    ".jsonl",
    ".txt", ".log", ".ndjson", ".htm",
    ".py",
    ".mojo",
    ".sql",
    ".sh",
    ".ps1",
    ".ts",
    ".js",
    ".tsx", ".jsx", ".rs", ".go", ".c", ".h", ".cpp", ".hpp",
    ".toml", ".yaml", ".yml", ".ini", ".css", ".html", ".xml",
}
SUPPORTED_EXTENSIONS |= BINARY_EXTENSIONS


def ingest_document_file(filepath: Path | str, db_path: Path | str | None = None, *, doc_id: str | None = None, display_name: str | None = None) -> bool:
    """Ingests any supported file (.md, .csv, .json, .txt, code) into both vector and FTS5 indexes.

    Returns True if ingested/updated, False if unchanged.
    """
    path = Path(filepath)
    if not path.is_file():
        return False

    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        return False

    filename = doc_id if doc_id is not None else path.name
    if not isinstance(filename, str) or not filename or len(filename) > 4096 or '\x00' in filename:
        raise ValueError('Invalid document identity')
    from app import config
    if config.EMBEDDING_PROVIDER != "local":
        raise ValueError("ROMS ingestion requires local embeddings")
    from app.document_parse import MAX_FILE_BYTES
    with path.open("rb") as source:
        raw = source.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError("Document exceeds the 32 MiB ingestion limit")
    identity = json.dumps([PARSER_VERSION, config.EMBEDDING_PROVIDER, config.EMBEDDING_MODEL_NAME,
                           config.EMBEDDING_DIM], ensure_ascii=False).encode('utf-8')
    checksum = hashlib.sha256(identity + b'\0' + raw).hexdigest()

    from app.config import EMBEDDING_DIM
    from app.topic import tag_chunks_with_topics

    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT checksum FROM okf_registry WHERE doc_id = ?", (filename,))
    existing = cur.fetchone()
    if existing and existing[0] == checksum:
        return False

    parsed = parse_document(path)
    title, doc_type, raw_content, chunks = parsed.title, parsed.kind, parsed.text, parsed.chunks
    if parsed.raw != raw:
        raise ValueError("Document changed during extraction; retry after writing completes")
    if display_name:
        title = title.replace(path.name, display_name)
    if not raw_content or not chunks:
        raise ValueError("No searchable text recovered; previous index was retained")

    # Finish all model work and validate every vector before touching the old index.
    import torch
    model = get_embedding_model()
    chunks = fit_model_window(chunks, model)
    with torch.inference_mode():
        batch_embeddings = np.asarray(
            model.encode(chunks, output_value="sentence_embedding", batch_size=32),
            dtype=np.float32,
        )

    expected_shape = (len(chunks), EMBEDDING_DIM)
    if batch_embeddings.shape != expected_shape or not np.isfinite(batch_embeddings).all():
        raise ValueError(f"Expected {len(chunks)} finite embeddings of dimension {EMBEDDING_DIM}")

    # Use a short-lived writer connection so ingestion does not close a pooled
    # connection that active search callers may share.
    conn = get_connection(db_path, reuse=False)
    cur = conn.cursor()
    # Recheck under a savepoint in case another indexer updated this document
    # while embeddings were being calculated. Replacement stays atomic.
    try:
        cur.execute("SAVEPOINT roms_ingest_document")
        cur.execute("SELECT checksum FROM okf_registry WHERE doc_id = ?", (filename,))
        existing = cur.fetchone()
        if existing and existing[0] == checksum:
            cur.execute("RELEASE SAVEPOINT roms_ingest_document")
            conn.commit()
            return False
        cur.execute("CREATE TABLE IF NOT EXISTS ingestion_details (doc_id TEXT PRIMARY KEY, parser_version TEXT, encoding TEXT, notes_json TEXT)")
        cur.execute("INSERT OR REPLACE INTO ingestion_details VALUES (?,?,?,?)",
                    (filename, PARSER_VERSION, parsed.encoding, json.dumps(parsed.notes)))
        old_topic_rows = cur.execute(
            "SELECT DISTINCT ct.topic_id FROM chunk_topics ct "
            "JOIN fts_chunks f USING(chunk_id) WHERE f.doc_id = ?",
            (filename,),
        ).fetchall()
        old_topic_ids = {row[0] for row in old_topic_rows}

        cur.execute(
            """
            INSERT INTO okf_registry (doc_id, title, doc_type, source_path, checksum)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(doc_id) DO UPDATE SET title=excluded.title, doc_type=excluded.doc_type,
                source_path=excluded.source_path, checksum=excluded.checksum,
                last_indexed=CURRENT_TIMESTAMP
            """,
            (filename, title, doc_type, str(path.resolve()), checksum),
        )
        cur.execute(
            "DELETE FROM chunk_topics WHERE chunk_id IN "
            "(SELECT chunk_id FROM fts_chunks WHERE doc_id = ?)", (filename,)
        )
        cur.execute("DELETE FROM vec_chunks WHERE doc_id = ?", (filename,))
        cur.execute("DELETE FROM fts_chunks WHERE doc_id = ?", (filename,))

        vector_rows = [
            (filename, vector.tobytes(), chunk_text)
            for chunk_text, vector in zip(chunks, batch_embeddings)
        ]
        cur.executemany(
            "INSERT INTO vec_chunks (doc_id, embedding, content) VALUES (?, ?, ?)",
            vector_rows,
        )
        first_chunk_id = cur.execute("SELECT last_insert_rowid()").fetchone()[0] - len(chunks) + 1
        chunk_ids = list(range(first_chunk_id, first_chunk_id + len(chunks)))
        cur.executemany(
            "INSERT INTO fts_chunks (chunk_id, doc_id, content) VALUES (?, ?, ?)",
            [(chunk_id, filename, chunk_text)
             for chunk_id, chunk_text in zip(chunk_ids, chunks)],
        )
        from app.knowledge_catalog import replace_navigation
        replace_navigation(conn, filename, list(zip(chunk_ids, chunks)))
        from app.knowledge_skills import replace_sources
        replace_sources(conn, filename, title, checksum, list(zip(chunk_ids, chunks)))
        tag_chunks_with_topics(
            list(zip(chunk_ids, chunks)), conn, doc_type=doc_type,
            refresh_topic_ids=old_topic_ids,
        )
        cur.execute("RELEASE SAVEPOINT roms_ingest_document")
        conn.commit()
    except BaseException:
        cur.execute("ROLLBACK TO SAVEPOINT roms_ingest_document")
        cur.execute("RELEASE SAVEPOINT roms_ingest_document")
        raise
    finally:
        conn.close()

    # Ingestion commits the writer connection; drop local cached results.
    from app.rag_engine import clear_result_cache
    clear_result_cache()

    return True


# Backwards compatibility alias
ingest_okf_file = ingest_document_file


def ingest_okf_directory(
    directory_path: str | Path | None = None, db_path: Path | str | None = None
) -> int:
    """Scans and ingests all supported knowledge files (.md, .csv, .json, code, .txt) in the directory.

    Returns the number of files ingested or updated.
    """
    target_dir = Path(directory_path) if directory_path is not None else KNOWLEDGE_DIR
    # An unavailable root is not evidence that its documents were deleted.
    if not target_dir.exists():
        return 0
    files, identity = scan_knowledge_files(target_dir)
    ingested_count = 0
    for file_path in files:
        if ingest_managed_file(file_path, target_dir, db_path):
            ingested_count += 1

    prune_missing_knowledge(target_dir, files, identity, db_path)
    return ingested_count


def scan_knowledge_files(root):
    """Return a complete scan and its root identity; never accept a partial walk."""
    root = Path(root)
    before = root.stat()
    files = list(knowledge_files(root))
    after = root.stat()
    identity = (before.st_dev, before.st_ino)
    if identity != (after.st_dev, after.st_ino):
        raise OSError('Knowledge root changed during scanning; retry')
    return files, identity


def prune_missing_knowledge(root, files, identity, db_path=None):
    """Reconcile a completed scan, only for identities owned by this directory.

    Independently imported snapshots and documents belonging to another root are
    preserved. Recheck absence under the writer lock and invalidate search caches
    only after all related index records have committed together.
    """
    root = Path(root)
    present = {Path(path).relative_to(root).as_posix() for path in files}
    root = root.resolve()

    def check_root():
        current = root.stat()
        if (current.st_dev, current.st_ino) != identity:
            raise OSError('Knowledge root changed during reconciliation; retry')

    check_root()
    conn = get_connection(db_path, reuse=False)
    removed = 0
    try:
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for doc_id, source in conn.execute('SELECT doc_id,source_path FROM okf_registry').fetchall():
                if not source or doc_id in present:
                    continue
                path = Path(source)
                try:
                    relative = path.relative_to(root)
                except ValueError:
                    continue
                # Existing managed documents need no migration. Namespaced UI and
                # library imports cannot be mistaken for root-relative identities.
                if relative.as_posix() != doc_id or '..' in relative.parts:
                    continue
                try:
                    path.lstat()  # A reappeared file/link is not a confirmed deletion.
                    continue
                except FileNotFoundError:
                    pass
                check_root()
                conn.execute('DELETE FROM chunk_topics WHERE chunk_id IN (SELECT chunk_id FROM fts_chunks WHERE doc_id=?)', (doc_id,))
                for table in ('vec_chunks', 'fts_chunks', 'okf_registry', 'ingestion_details', 'knowledge_navigation', 'knowledge_skill_sources'):
                    if table in tables:
                        conn.execute(f'DELETE FROM {table} WHERE doc_id=?', (doc_id,))
                if 'ingestion_failures' in tables:
                    conn.execute('DELETE FROM ingestion_failures WHERE source_path=?', (source,))
                removed += 1
            if 'ingestion_failures' in tables:
                # Failed first imports have no registry row, but their diagnostics
                # should disappear when the failed source is deliberately removed.
                for (source,) in conn.execute('SELECT source_path FROM ingestion_failures').fetchall():
                    path = Path(source)
                    try:
                        relative = path.relative_to(root)
                    except ValueError:
                        continue
                    if relative.as_posix() in present or '..' in relative.parts:
                        continue
                    try:
                        path.lstat()
                    except FileNotFoundError:
                        conn.execute('DELETE FROM ingestion_failures WHERE source_path=?', (source,))
            if removed:
                conn.execute('UPDATE topics SET chunk_count=(SELECT COUNT(*) FROM chunk_topics WHERE chunk_topics.topic_id=topics.topic_id)')
            check_root()
    finally:
        conn.close()
    if removed:
        from app.rag_engine import clear_result_cache
        clear_result_cache()
    return removed


def knowledge_files(root):
    """Walk the user knowledge folder without following links or dependency folders."""
    root = Path(root)
    count = 0
    def scan_error(error):
        raise error

    for parent, dirs, files in os.walk(root, followlinks=False, onerror=scan_error):
        dirs[:] = sorted(name for name in dirs if not name.startswith('.') and name not in
                         {'node_modules', 'venv', '__pycache__', 'target', 'build', 'dist'}
                         and not (Path(parent) / name).is_symlink())
        for name in sorted(files):
            path = Path(parent) / name
            if name.startswith('.') or path.is_symlink() or not path.is_file():
                continue
            count += 1
            if count > 10000:
                raise ValueError('Knowledge folder exceeds the 10,000-file scan limit')
            yield path


def _failure_table(conn):
    conn.execute('CREATE TABLE IF NOT EXISTS ingestion_failures (source_path TEXT PRIMARY KEY, error TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)')


def ingest_managed_file(path, root, db_path=None):
    """Return True for indexed, False for unchanged, None for a recorded failure."""
    import sys
    path, root = Path(path), Path(root)
    try:
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise ValueError(f'Unsupported file extension {path.suffix or "(none)"}; use a supported text, PDF, Office or image format')
        changed = ingest_document_file(path, db_path, doc_id=path.relative_to(root).as_posix())
    except Exception as error:
        conn = get_connection(db_path)
        _failure_table(conn)
        conn.execute('INSERT OR REPLACE INTO ingestion_failures(source_path,error,updated_at) VALUES (?,?,CURRENT_TIMESTAMP)',
                     (str(path.resolve()), f'{type(error).__name__}: {error}'[:2000]))
        conn.commit()
        print(f'[ROMS ingestion] {path.name}: {error}', file=sys.stderr)
        return None
    conn = get_connection(db_path)
    _failure_table(conn)
    conn.execute('DELETE FROM ingestion_failures WHERE source_path=?', (str(path.resolve()),))
    conn.commit()
    return changed


def get_ingestion_status(db_path=None):
    conn = get_connection(db_path)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    failures = [] if 'ingestion_failures' not in tables else [
        {'source_path': path, 'error': error, 'updated_at': updated}
        for path, error, updated in conn.execute('SELECT source_path,error,updated_at FROM ingestion_failures ORDER BY updated_at DESC LIMIT 100')]
    notes = [] if 'ingestion_details' not in tables else [
        {'doc_id': doc, 'encoding': encoding, 'notes': json.loads(value)}
        for doc, encoding, value in conn.execute("SELECT doc_id,encoding,notes_json FROM ingestion_details WHERE notes_json != '[]' LIMIT 100")]
    count = 0 if 'ingestion_failures' not in tables else conn.execute('SELECT count(*) FROM ingestion_failures').fetchone()[0]
    return {'failure_count': count, 'failures': failures, 'extraction_notes': notes}
