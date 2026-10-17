"""Source-linked navigation, updated in the same transaction as the search index."""
import re
from app.db import get_connection


def replace_navigation(conn, doc_id, chunks):
    conn.execute('CREATE TABLE IF NOT EXISTS knowledge_navigation (doc_id TEXT, chunk_id INTEGER, kind TEXT, label TEXT, detail TEXT)')
    conn.execute('CREATE INDEX IF NOT EXISTS navigation_doc ON knowledge_navigation(doc_id)')
    conn.execute('DELETE FROM knowledge_navigation WHERE doc_id=?', (doc_id,))
    rows = []
    seen = set()
    for chunk_id, content in chunks:
        for line in content.splitlines():
            heading = re.fullmatch(r'\s{0,3}#{1,6}\s+(.{1,200})', line)
            definition = re.fullmatch(r'\s*(?:[-*]\s+)?(?:\*\*)?([\w][\w /()-]{1,79}?)(?:\*\*)?\s+(?:means|is defined as|refers to)\s+(.{3,1000})', line)
            if heading:
                item = ('section', heading[1].rstrip('# ').strip(), '')
            elif definition:
                item = ('definition', definition[1].strip(), definition[2].strip())
            else:
                continue
            if item not in seen and len(rows) < 1000:
                seen.add(item)
                rows.append((doc_id, chunk_id, *item))
    conn.executemany('INSERT INTO knowledge_navigation VALUES (?,?,?,?,?)', rows)


def catalog(db_path=None, offset=0, limit=50):
    offset, limit = max(0, int(offset)), max(1, min(int(limit), 100))
    conn = get_connection(db_path, reuse=False)
    try:
        documents = [dict(zip(('doc_id', 'title', 'type', 'indexed_at'), row)) for row in conn.execute(
            'SELECT doc_id,title,doc_type,last_indexed FROM okf_registry ORDER BY doc_id LIMIT ? OFFSET ?', (limit, offset))]
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for document in documents:
            # Joining the live chunks also hides stale navigation after legacy source removal.
            document['navigation'] = [] if 'knowledge_navigation' not in tables else [
                dict(zip(('chunk_id', 'kind', 'label', 'detail'), row)) for row in conn.execute(
                    'SELECT n.chunk_id,n.kind,n.label,n.detail FROM knowledge_navigation n '
                    'JOIN fts_chunks f ON f.doc_id=n.doc_id AND f.chunk_id=n.chunk_id '
                    'WHERE n.doc_id=? ORDER BY n.rowid', (document['doc_id'],))]
        return {'total': conn.execute('SELECT count(*) FROM okf_registry').fetchone()[0],
                'offset': offset, 'documents': documents}
    finally:
        conn.close()
