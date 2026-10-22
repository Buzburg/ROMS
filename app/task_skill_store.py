"""Immutable task-skill candidates, live-source checks and revision-bound observations.

Saving retains authored text, not copies of source documents. No candidate is
installed, executed or promoted based on self-reported feedback.
"""
import json
import re

from app.db import get_connection
from app import task_skills as tasks


def _schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS task_skill_candidates (
        id TEXT PRIMARY KEY, title TEXT NOT NULL, task TEXT NOT NULL,
        manifest_json TEXT NOT NULL, skill_json TEXT NOT NULL, parent_id TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS task_skill_observations (
        event_id TEXT PRIMARY KEY, skill_id TEXT NOT NULL, outcome TEXT NOT NULL,
        note TEXT NOT NULL, evidence TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
    conn.execute('CREATE INDEX IF NOT EXISTS task_skill_observation_key ON task_skill_observations(skill_id)')


def _exists(conn):
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE name='task_skill_candidates'").fetchone())


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r'task-[0-9a-f]{24}', value):
        raise ValueError('Invalid task skill ID')
    return value


def _detail(conn, skill_id):
    row = conn.execute('SELECT title,task,manifest_json,skill_json,parent_id,created_at '
                       'FROM task_skill_candidates WHERE id=?', (skill_id,)).fetchone()
    if row is None:
        return None
    title, task, raw_manifest, raw_skill, parent, created = row
    summary = {'id': skill_id, 'title': title, 'task': task, 'parent_id': parent,
               'created_at': created, 'persisted': True, 'execution_ready': False}
    manifest = tasks._decode(raw_manifest)
    # Original user constraints remain necessary when revising a stale candidate.
    summary['constraints'] = manifest['constraints']
    sources = []
    for ref in manifest['sources']:
        source = tasks._source(conn, ref['doc_id'], ref['id'])
        if source is None or {k: v for k, v in source.items() if k != 'text'} != ref:
            return {**summary, 'status': 'stale',
                    'reason': 'Source changed or disappeared; prepare and author a new revision.'}
        sources.append(source)
    packet = {**manifest, 'sources': sources}
    result = tasks.finalize(json.dumps(packet), raw_skill, _connection=conn)
    if (result.get('id') != skill_id or result['task'] != task
            or result['skill']['title'] != title):
        raise ValueError('Stored task skill identity does not match its validated content')
    feedback = dict(conn.execute('SELECT outcome,count(*) FROM task_skill_observations '
                                'WHERE skill_id=? GROUP BY outcome', (skill_id,)))
    observations = [{'outcome': outcome, 'note': note, 'evidence': evidence, 'created_at': at}
                    for outcome, note, evidence, at in conn.execute(
                        'SELECT outcome,note,evidence,created_at FROM task_skill_observations '
                        'WHERE skill_id=? ORDER BY rowid DESC LIMIT 10', (skill_id,))]
    return {**result, **summary, 'constraints': packet['constraints'],
            'feedback': feedback, 'observations': observations,
            'verification': 'Source identity and structure checked. Observations are self-reported, not independent verification.',
            'reuse': 'Review the original task and constraints before reuse. Prepare again for different inputs or changed evidence.'}


def save(packet_json, skill_json, parent_id=None, db_path=None):
    if parent_id is not None:
        _id(parent_id)
    conn = get_connection(db_path, reuse=False)
    try:
        conn.execute('BEGIN IMMEDIATE')
        result = tasks.finalize(packet_json, skill_json, _connection=conn)
        if result['status'] != 'candidate':
            raise ValueError('Resolve unknowns before saving a task skill')
        _schema(conn)
        if parent_id == result['id']:
            raise ValueError('A candidate cannot be its own parent')
        packet = tasks._decode(packet_json)
        manifest = {**packet, 'sources': [{k: v for k, v in s.items() if k != 'text'}
                                          for s in packet['sources']]}
        previous = conn.execute('SELECT parent_id FROM task_skill_candidates WHERE id=?',
                                (result['id'],)).fetchone()
        if previous is not None and previous[0] != parent_id:
            raise ValueError('Existing candidate has different immutable parent lineage')
        if previous is None and parent_id is not None and not conn.execute(
                'SELECT 1 FROM task_skill_candidates WHERE id=?', (parent_id,)).fetchone():
            raise ValueError('Parent candidate does not exist')
        conn.execute('INSERT OR IGNORE INTO task_skill_candidates '
                     '(id,title,task,manifest_json,skill_json,parent_id) VALUES (?,?,?,?,?,?)',
                     (result['id'], result['skill']['title'], packet['task'],
                      json.dumps(manifest), json.dumps(result['skill']), parent_id))
        saved = _detail(conn, result['id'])
        conn.commit()
        return {**saved, 'saved': previous is None}
    finally:
        conn.close()


def get(skill_id, db_path=None):
    _id(skill_id)
    conn = get_connection(db_path, reuse=False)
    try:
        conn.execute('BEGIN')
        return _detail(conn, skill_id) if _exists(conn) else None
    finally:
        conn.close()


def search(query='', offset=0, limit=20, db_path=None):
    if not isinstance(query, str) or len(query) > 500 or '\x00' in query:
        raise ValueError('Query must be text up to 500 characters')
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError('Offset must be nonnegative and limit must be 1–50')
    conn = get_connection(db_path, reuse=False)
    try:
        conn.execute('BEGIN')
        if not _exists(conn):
            return {'total': 0, 'offset': offset, 'skills': []}
        terms = list(dict.fromkeys(re.findall(r'\w+', query.casefold())))[:12]
        predicates, params = [], []
        for term in terms:
            pattern = '%' + term.replace('_', '\\_') + '%'
            predicates.append("(lower(title) LIKE ? ESCAPE '\\' OR lower(task) LIKE ? ESCAPE '\\')")
            params.extend([pattern, pattern])
        where = ' WHERE ' + ' AND '.join(predicates) if predicates else ''
        total = conn.execute('SELECT count(*) FROM task_skill_candidates' + where, params).fetchone()[0]
        rows = conn.execute('SELECT id FROM task_skill_candidates' + where +
                            ' ORDER BY created_at DESC,id LIMIT ? OFFSET ?', (*params, limit, offset)).fetchall()
        summaries = []
        for (skill_id,) in rows:
            detail = _detail(conn, skill_id)
            summaries.append({k: v for k, v in detail.items() if k in {
                'id', 'title', 'task', 'constraints', 'status', 'parent_id', 'created_at',
                'feedback', 'reason', 'execution_ready'}})
        return {'total': total, 'offset': offset, 'skills': summaries,
                'coverage': 'Total includes stale records. Search matches title and original task; it does not establish applicability.'}
    finally:
        conn.close()


def record_feedback(skill_id, outcome, event_id, note='', evidence='', db_path=None):
    _id(skill_id)
    if outcome not in ('helpful', 'needs_work'):
        raise ValueError('Outcome must be helpful or needs_work')
    if not isinstance(event_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', event_id):
        raise ValueError('A stable event_id of 1–80 letters, digits, hyphens or underscores is required')
    for label, value in (('note', note), ('evidence', evidence)):
        if not isinstance(value, str) or len(value) > 2000 or '\x00' in value:
            raise ValueError(label + ' must be text up to 2000 characters')
    conn = get_connection(db_path, reuse=False)
    try:
        conn.execute('BEGIN IMMEDIATE')
        current = _detail(conn, skill_id) if _exists(conn) else None
        if current is None or current['status'] != 'candidate':
            raise ValueError('Task skill is missing or stale; prepare a new revision')
        previous = conn.execute('SELECT skill_id,outcome,note,evidence FROM task_skill_observations '
                                'WHERE event_id=?', (event_id,)).fetchone()
        values = (skill_id, outcome, note, evidence)
        if previous is not None and previous != values:
            raise ValueError('event_id already belongs to different feedback')
        conn.execute('INSERT OR IGNORE INTO task_skill_observations '
                     '(event_id,skill_id,outcome,note,evidence) VALUES (?,?,?,?,?)', (event_id, *values))
        conn.commit()
        return {'recorded': previous is None, 'id': skill_id, 'independently_verified': False}
    finally:
        conn.close()


def forget(skill_id, db_path=None):
    _id(skill_id)
    conn = get_connection(db_path, reuse=False)
    try:
        conn.execute('BEGIN IMMEDIATE')
        if not _exists(conn):
            return {'forgotten': False}
        conn.execute('DELETE FROM task_skill_observations WHERE skill_id=?', (skill_id,))
        deleted = conn.execute('DELETE FROM task_skill_candidates WHERE id=?', (skill_id,)).rowcount
        conn.commit()
        return {'forgotten': bool(deleted)}
    finally:
        conn.close()


def find_for_packet(packet, parent_id=None, db_path=None):
    """Reuse only exact current evidence/request matches, without adverse feedback."""
    conn = get_connection(db_path, reuse=False)
    try:
        conn.execute('BEGIN')
        if not _exists(conn):
            return None
        rows = conn.execute('SELECT id FROM task_skill_candidates WHERE task=? '
                            'ORDER BY created_at DESC,rowid DESC LIMIT 50', (packet['task'],)).fetchall()
        for (skill_id,) in rows:
            detail = _detail(conn, skill_id)
            if (detail['status'] == 'candidate' and detail['source_revision'] == packet['revision']
                    and (detail['parent_id'] == parent_id or detail['id'] == parent_id)
                    and not detail['feedback'].get('needs_work')):
                return detail
        return None
    finally:
        conn.close()
