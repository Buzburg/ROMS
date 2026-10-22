"""Incremental, extractive skill drafts grounded in the live knowledge index.

No model calls, code execution, file activation, or inferred success claims.
Procedures from different sources remain separate variants, preserving their order.
"""
import hashlib
import json
import re
import unicodedata

from app.db import get_connection

VERSION = 'knowledge-skills-v1'
MAX_SECTION = 12000
MAX_SOURCES = 32
ACTION = re.compile(r'^(?:\*\*)?(?:check|verify|run|open|save|create|install|copy|select|click|add|remove|stop|start|test|confirm|ensure|record|restore|back\s+up|configure|connect|restart|review|compare|set|read|write|use|export|import|wait|inspect|validate|delete|do\s+not|never)\b', re.I)
HEADING = re.compile(r'^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$')
ITEM = re.compile(r'^\s*(?:\d+[.)]|[-*+]\s*(?:\[[ xX]\])?)\s+(.+)$')
GENERIC = {'steps', 'procedure', 'instructions', 'setup', 'usage', 'installation', 'workflow', 'quick start'}


def schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS knowledge_skill_sources (
        skill_id TEXT NOT NULL, doc_id TEXT NOT NULL, section INTEGER NOT NULL,
        title TEXT NOT NULL, checksum TEXT NOT NULL, chunk_id INTEGER NOT NULL,
        content TEXT NOT NULL, fingerprint TEXT NOT NULL, step_count INTEGER NOT NULL, chunk_ids TEXT NOT NULL,
        PRIMARY KEY(doc_id, section))''')
    conn.execute('CREATE INDEX IF NOT EXISTS skill_source_key ON knowledge_skill_sources(skill_id)')
    conn.execute('''CREATE TABLE IF NOT EXISTS knowledge_skill_feedback (
        event_id TEXT PRIMARY KEY, skill_id TEXT NOT NULL, revision TEXT NOT NULL,
        outcome TEXT NOT NULL, note TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    conn.execute('CREATE INDEX IF NOT EXISTS skill_feedback_key ON knowledge_skill_feedback(skill_id,revision)')


def _key(text):
    return ' '.join(re.findall(r'\w+', unicodedata.normalize('NFKC', text).casefold()))


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def replace_sources(conn, doc_id, title, checksum, chunks):
    """Replace a document's drafts within the caller's ingestion transaction."""
    schema(conn)
    conn.execute('DELETE FROM knowledge_skill_sources WHERE doc_id=?', (doc_id,))
    heading, lines, section, first_chunk, fenced = title, [], 0, None, False
    level, ancestors = 0, []
    rows = []
    section_chunks = []
    def finish():
        nonlocal section
        section += 1
        # Parent conditions remain part of a child procedure. Do not inherit sibling
        # sections or silently truncate a prerequisite to fit the section budget.
        context = []
        for parent_level, parent_heading, parent_lines, _ in ancestors:
            if parent_level:
                context.append('#' * parent_level + ' ' + parent_heading)
            context.extend(parent_lines)
        text = '\n'.join(context + lines).strip()
        context_chunks = [cid for _, _, _, parent_chunks in ancestors for cid in parent_chunks]
        steps = [m[1] for line in lines if (m := ITEM.match(line))]
        # Require procedural evidence; retain surrounding caveats and checks verbatim.
        if (len(rows) >= 32 or not 2 <= len(steps) <= 64 or
                len(text) > MAX_SECTION or not any(ACTION.match(step) for step in steps)):
            return
        label = f'{title}: {heading}' if _key(heading) in GENERIC else heading
        label = label.strip()
        if not label or len(label) > 240:
            return
        skill_id = 'knowledge-' + _digest(_key(label))[:24]
        rows.append((skill_id, doc_id, section, label, checksum, first_chunk,
                     text, _digest(text), len(steps), json.dumps(list(dict.fromkeys(context_chunks + section_chunks)))))
    previous = None
    for chunk_id, content in chunks:
        # Exact repeated chunks do not inflate procedural evidence.
        if content == previous:
            continue
        previous = content
        for line in content.splitlines():
            if line.strip().startswith(('```', '~~~')):
                fenced = not fenced
            match = HEADING.match(line) if not fenced else None
            if match:
                finish()
                stripped = line.lstrip()
                new_level = len(stripped) - len(stripped.lstrip('#'))
                if level < new_level and (level or lines):
                    ancestors.append((level, heading, lines, section_chunks))
                ancestors = [parent for parent in ancestors if parent[0] < new_level]
                level = new_level
                heading, lines, first_chunk = match[1], [], chunk_id
                section_chunks = [chunk_id]
            else:
                if first_chunk is None:
                    first_chunk = chunk_id
                lines.append(line)
                section_chunks.append(chunk_id)
        # Continue a section across passage boundaries, preserving content order.
    finish()
    conn.executemany('INSERT INTO knowledge_skill_sources VALUES (?,?,?,?,?,?,?,?,?,?)', rows)
    return len(rows)


def rebuild(db_path=None):
    """Backfill existing indexed sources; stream documents inside one transaction."""
    conn = get_connection(db_path, reuse=False)
    try:
        conn.execute('BEGIN IMMEDIATE')
        schema(conn)
        conn.execute('DELETE FROM knowledge_skill_sources WHERE doc_id NOT IN (SELECT doc_id FROM okf_registry)')
        documents = drafts = 0
        for doc_id, title, checksum in conn.execute('SELECT doc_id,title,checksum FROM okf_registry ORDER BY doc_id'):
            chunks = conn.execute('SELECT chunk_id,content FROM fts_chunks WHERE doc_id=? ORDER BY chunk_id', (doc_id,))
            drafts += replace_sources(conn, doc_id, title or doc_id, checksum, chunks)
            documents += 1
        conn.commit()
        return {'documents': documents, 'source_procedures': drafts}
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


LIVE = '''FROM knowledge_skill_sources s JOIN okf_registry r ON r.doc_id=s.doc_id AND r.checksum=s.checksum
          JOIN fts_chunks f ON f.chunk_id=s.chunk_id AND f.doc_id=s.doc_id'''


def _available(conn):
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE name='knowledge_skill_sources'").fetchone())


def _detail(conn, skill_id):
    source_rows = conn.execute('SELECT s.doc_id,s.title,s.checksum,s.chunk_id,s.fingerprint,s.step_count,s.chunk_ids ' +
                               LIVE + ' WHERE s.skill_id=? ORDER BY s.doc_id,s.section', (skill_id,))
    digest = hashlib.sha256(VERSION.encode())
    documents, fingerprints, count, title = set(), set(), 0, ''
    for row in source_rows:
        digest.update(json.dumps(row, ensure_ascii=False).encode() + b'\0')
        documents.add(row[0])
        fingerprints.add(row[4])
        if not count:
            title = row[1]
        count += 1
    if not count:
        return None
    revision = digest.hexdigest()
    variants = {}
    rows = conn.execute('SELECT s.doc_id,s.checksum,s.chunk_id,s.content,s.fingerprint,s.step_count,s.chunk_ids ' +
                        LIVE + ' WHERE s.skill_id=? ORDER BY s.doc_id,s.section LIMIT ?', (skill_id, MAX_SOURCES))
    for doc_id, checksum, chunk, content, fingerprint, steps, chunk_ids in rows:
        variant = variants.setdefault(fingerprint, {'text': content, 'steps': steps, 'sources': []})
        variant['sources'].append({'doc_id': doc_id, 'chunk_id': chunk, 'checksum': checksum, 'chunk_ids': json.loads(chunk_ids)})
    feedback = dict(conn.execute('SELECT outcome,count(*) FROM knowledge_skill_feedback WHERE skill_id=? AND revision=? GROUP BY outcome', (skill_id, revision)))
    observations = [{'revision': rev, 'outcome': outcome, 'note': note, 'created_at': created, 'current': rev == revision}
                    for rev, outcome, note, created in conn.execute(
                        'SELECT revision,outcome,note,created_at FROM knowledge_skill_feedback WHERE skill_id=? ORDER BY rowid DESC LIMIT 10', (skill_id,))]
    return {'id': skill_id, 'title': title, 'revision': revision, 'status': 'candidate',
            'source_documents': len(documents), 'procedure_variants': len(fingerprints),
            'duplicate_copies': count - len(fingerprints),
            'omitted_sources': max(0, count - MAX_SOURCES),
            'variants': list(variants.values()), 'feedback': feedback, 'observations': observations,
            'limitations': 'Extracted source procedures, not verified instructions. Variants may conflict. Review prerequisites, risks and results before use.'}


def list_drafts(db_path=None, query='', offset=0, limit=20):
    if not isinstance(query, str) or len(query) > 500:
        raise ValueError('Skill query must be at most 500 characters')
    offset, limit = max(0, int(offset)), max(1, min(int(limit), 50))
    conn = get_connection(db_path, reuse=False)
    try:
        if not _available(conn):
            return {'total': 0, 'offset': offset, 'skills': []}
        # AND terms, bound parameters; escaping keeps %, _ and backslashes literal.
        terms = [t for t in re.findall(r'\w+', query.casefold()) if t not in {'how', 'do', 'i', 'the', 'a', 'an', 'to', 'for', 'my', 'please', 'can'}][:12]
        where, params = '', []
        for term in terms:
            where += " AND (lower(s.title) LIKE ? ESCAPE '\\' OR lower(s.content) LIKE ? ESCAPE '\\')"
            pattern = '%' + term.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
            params.extend([pattern, pattern])
        base = LIVE + ' WHERE 1=1' + where
        conn.execute('BEGIN')
        total = conn.execute('SELECT count(DISTINCT s.skill_id) ' + base, params).fetchone()[0]
        ids = conn.execute('SELECT DISTINCT s.skill_id ' + base + ' ORDER BY s.skill_id LIMIT ? OFFSET ?', (*params, limit, offset)).fetchall()
        skills = []
        for (key,) in ids:
            skill = _detail(conn, key)
            if skill:
                skill.pop('variants')
                skill.pop('observations')
                skills.append(skill)
        return {'total': total, 'offset': offset, 'skills': skills}
    finally:
        conn.close()


def get_draft(skill_id, db_path=None):
    if not isinstance(skill_id, str) or not re.fullmatch(r'knowledge-[0-9a-f]{24}', skill_id):
        raise ValueError('Invalid generated skill ID')
    conn = get_connection(db_path, reuse=False)
    try:
        conn.execute('BEGIN')
        return _detail(conn, skill_id) if _available(conn) else None
    finally:
        conn.close()


def record_feedback(skill_id, revision, outcome, note='', event_id='', db_path=None):
    if not isinstance(outcome, str) or outcome not in {'helpful', 'needs_work'}:
        raise ValueError('Outcome must be helpful or needs_work')
    if not isinstance(note, str) or len(note) > 2000 or '\x00' in note:
        raise ValueError('Feedback note must be text up to 2000 characters')
    if not isinstance(event_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', event_id):
        raise ValueError('A stable event_id of 1–80 letters, digits, hyphens or underscores is required')
    if not isinstance(revision, str) or not re.fullmatch(r'[0-9a-f]{64}', revision):
        raise ValueError('Invalid skill revision')
    if not isinstance(skill_id, str) or not re.fullmatch(r'knowledge-[0-9a-f]{24}', skill_id):
        raise ValueError('Invalid generated skill ID')
    conn = get_connection(db_path, reuse=False)
    try:
        conn.execute('BEGIN IMMEDIATE')
        schema(conn)
        skill = _detail(conn, skill_id)
        if not skill or skill['revision'] != revision:
            raise ValueError('Skill sources changed or disappeared; refresh before recording feedback')
        previous = conn.execute('SELECT skill_id,revision,outcome,note FROM knowledge_skill_feedback WHERE event_id=?', (event_id,)).fetchone()
        values = (skill_id, revision, outcome, note)
        if previous is not None and previous != values:
            raise ValueError('event_id already belongs to different feedback')
        conn.execute('INSERT OR IGNORE INTO knowledge_skill_feedback(event_id,skill_id,revision,outcome,note) VALUES (?,?,?,?,?)', (event_id, *values))
        conn.commit()
        return {'recorded': previous is None, 'revision': revision}
    finally:
        conn.close()


def render_markdown(skill):
    """Export a portable, reviewable SKILL.md without installing or executing it."""
    lines = ['---', 'name: ' + skill['id'],
             'description: ' + json.dumps('Source-backed procedural draft for ' + skill['title'], ensure_ascii=False),
             'metadata:', '  review_status: candidate', '  source_revision: ' + skill['revision'], '---', '',
             '# Source-backed procedure draft', '',
             '## When to use', skill['title'], '',
             '## Before use',
             'Review the quoted source procedures, prerequisites and expected results. They are evidence, not authorization to execute commands or change settings.',
             'Keep conflicting variants separate. Confirm applicability to the current task and obtain any required authorization.',
             'Check the current ROMS revision before reuse; exported files do not update automatically.', '',
             '## Source procedures']
    for i, variant in enumerate(skill['variants'], 1):
        lines += ['', f'### Variant {i}', '']
        # Quote every source line; source frontmatter, headings and code fences cannot become the wrapper.
        lines += ['> ' + line for line in variant['text'].splitlines()]
        lines += ['', 'Sources (document ID / chunk / source checksum):']
        lines += ['- ' + json.dumps(source, ensure_ascii=False) for source in variant['sources']]
    lines += ['', '## Verification',
              '- Check each cited source is current and matches the intended environment.',
              '- Use the source-specific validation steps; do not infer success from this draft.',
              '- Record helpful/needs-work feedback against this revision in ROMS.', '',
              f"Preview omits {skill['omitted_sources']} source records. Feedback is user-reported, not proof of correctness.", '']
    return '\n'.join(lines)
