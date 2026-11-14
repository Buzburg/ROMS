"""Persist source locations and expand indexed citations without reading files."""
import json


def schema(conn):
    conn.execute('CREATE TABLE IF NOT EXISTS chunk_sources ('
                 'chunk_id INTEGER PRIMARY KEY, doc_id TEXT NOT NULL, ordinal INTEGER NOT NULL, '
                 'parent_id TEXT NOT NULL, metadata_json TEXT NOT NULL)')
    conn.execute('CREATE INDEX IF NOT EXISTS chunk_source_parent ON chunk_sources(doc_id,parent_id,ordinal)')


def replace(conn, doc_id, chunk_ids, metadata):
    if len(chunk_ids) != len(metadata):
        raise ValueError('Source metadata does not match indexed chunks')
    schema(conn)
    conn.execute('DELETE FROM chunk_sources WHERE doc_id=?', (doc_id,))
    conn.executemany('INSERT INTO chunk_sources VALUES (?,?,?,?,?)',
        [(cid, doc_id, ordinal, source['parent_id'], json.dumps(source, ensure_ascii=False))
         for ordinal, (cid, source) in enumerate(zip(chunk_ids, metadata))])


def locations(conn, chunk_ids):
    if not chunk_ids or not conn.execute("SELECT 1 FROM sqlite_master WHERE name='chunk_sources'").fetchone():
        return {}
    return {cid: json.loads(raw) for cid, raw in conn.execute(
        'SELECT s.chunk_id,s.metadata_json FROM chunk_sources s JOIN fts_chunks f '
        'ON f.chunk_id=s.chunk_id AND f.doc_id=s.doc_id '
        'WHERE s.chunk_id IN (SELECT value FROM json_each(?))', (json.dumps(chunk_ids),))}


def expand(chunk_id, neighbors=1, max_chars=6000, db_path=None):
    """Return the selected chunk and bounded neighbors in its source section.

    Existing indexes without metadata return only the requested evidence.
    Oversized requested chunks raise, rather than silently clipping citations.
    """
    from app.db import get_connection
    if type(chunk_id) is not int or not 0 < chunk_id < 2**63:
        raise ValueError('A positive chunk ID is required')
    if type(neighbors) is not int or not 0 <= neighbors <= 3:
        raise ValueError('Select 0–3 neighbors on each side')
    if type(max_chars) is not int or not 1 <= max_chars <= 20000:
        raise ValueError('Source character budget must be between 1 and 20000')
    conn = get_connection(db_path, reuse=False)
    try:
        conn.execute('BEGIN')
        row = conn.execute('SELECT doc_id,content FROM fts_chunks WHERE chunk_id=?', (chunk_id,)).fetchone()
        if row is None:
            raise ValueError('Source is no longer indexed; search again')
        doc_id, content = row
        if len(content) > max_chars:
            raise ValueError('Selected source exceeds the character budget; nothing was clipped')
        metadata = locations(conn, [chunk_id])
        rows = [(chunk_id, content)]
        if chunk_id in metadata and neighbors:
            parent = conn.execute('SELECT parent_id,ordinal FROM chunk_sources WHERE chunk_id=?', (chunk_id,)).fetchone()
            rows = conn.execute('SELECT f.chunk_id,f.content FROM chunk_sources s JOIN fts_chunks f '
                'ON f.chunk_id=s.chunk_id AND f.doc_id=s.doc_id '
                'WHERE s.doc_id=? AND s.parent_id=? AND s.ordinal BETWEEN ? AND ? ORDER BY s.ordinal',
                (doc_id, parent[0], parent[1] - neighbors, parent[1] + neighbors)).fetchall()
        chosen, used = {chunk_id}, len(content)
        for cid, text in rows:
            if cid != chunk_id and used + len(text) <= max_chars:
                chosen.add(cid)
                used += len(text)
        metadata = locations(conn, list(chosen))
        return {'sources': [dict(chunk_id=cid, doc_id=doc_id, content=text, source=metadata.get(cid, {}))
                            for cid, text in rows if cid in chosen],
                'source_characters': used, 'budget_limited': len(chosen) < len(rows)}
    finally:
        conn.close()
