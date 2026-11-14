"""Semantic tool discovery in ROMS's pinned EmbeddingGemma 2 space."""
from copy import deepcopy
import hashlib
import json
import re
from collections import OrderedDict
from threading import RLock

import numpy as np

from app import config
from app.db import get_connection
from app.embedding_space import identity, require_compatible

_RESULTS = OrderedDict()
_RESULTS_LOCK = RLock()


def clear_results():
    with _RESULTS_LOCK:
        _RESULTS.clear()


def _unit(value):
    vector = np.asarray(value, dtype=np.float32)
    if vector.shape != (config.EMBEDDING_DIM,) or not np.isfinite(vector).all():
        raise ValueError('Tool embedding has invalid shape or nonfinite values')
    norm = float(np.linalg.norm(vector))
    if not np.isfinite(norm) or norm == 0:
        raise ValueError('Tool embedding is a zero vector')
    return vector / norm


def _descriptor(row):
    name, category, description, raw, *_ = row
    data = json.loads(raw or '{}')
    # Schemas remain in the registry; only descriptive text is embedded.
    return '\n'.join([name, category or '', description or '',
                      *[str(example) for example in data.get('examples', [])]])


def search(query, category='', limit=3, db_path=None):
    if not isinstance(query, str) or len(query) > 4096:
        raise ValueError('Tool query must be text of at most 4096 characters')
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('Tool limit must be between 1 and 100')
    if not query.strip():
        return []
    from app.rag_engine import _database_change_token, _get_query_embedding
    conn = get_connection(db_path)
    require_compatible(conn)
    namespace = identity()
    key = (_database_change_token(conn), namespace, query, category.casefold(), limit)
    use_cache = not conn.in_transaction
    if use_cache:
        with _RESULTS_LOCK:
            cached = _RESULTS.get(key)
            if cached is not None:
                _RESULTS.move_to_end(key)
                return deepcopy(cached)
    rows = conn.execute('SELECT r.tool_name,r.category,r.description,r.parameters_json,'
        'COALESCE(s.call_count,0),COALESCE(s.success_count,0),COALESCE(s.last_latency_ms,0) '
        'FROM tool_registry r LEFT JOIN tool_stats s USING(tool_name) '
        'WHERE r.is_active=1 ORDER BY r.rowid').fetchall()
    rows = [row for row in rows if not category or (row[1] or '').casefold() == category.casefold()]
    if not rows:
        return []
    conn.execute('CREATE TABLE IF NOT EXISTS tool_embeddings ('
        'tool_name TEXT PRIMARY KEY, model_identity TEXT NOT NULL, content_hash TEXT NOT NULL, vector BLOB NOT NULL)')
    texts = [_descriptor(row) for row in rows]
    hashes = [hashlib.sha256(text.encode()).hexdigest() for text in texts]
    stored = {name: (space, digest, blob) for name, space, digest, blob in conn.execute(
        'SELECT tool_name,model_identity,content_hash,vector FROM tool_embeddings')}
    vectors, missing = {}, []
    for index, row in enumerate(rows):
        entry = stored.get(row[0])
        if entry and entry[:2] == (namespace, hashes[index]):
            try:
                vectors[index] = _unit(np.frombuffer(entry[2], dtype=np.float32))
                continue
            except (TypeError, ValueError):
                pass  # Recompute corrupt cache entries using the real model.
        missing.append(index)
    if missing:
        from app.document_parse import fit_model_window
        model = config.get_embedding_model()
        pieces, groups = [], []
        for index in missing:
            fitted = fit_model_window([texts[index]], model)
            groups.append((index, len(pieces), len(fitted)))
            pieces.extend(fitted)
        encoded = np.asarray(model.encode(pieces, output_value='sentence_embedding', batch_size=32), dtype=np.float32)
        if encoded.shape != (len(pieces), config.EMBEDDING_DIM) or not np.isfinite(encoded).all():
            raise ValueError('Invalid tool descriptor embeddings')
        for index, start, length in groups:
            vectors[index] = _unit(encoded[start:start + length].mean(axis=0))
        conn.executemany('INSERT OR REPLACE INTO tool_embeddings VALUES (?,?,?,?)',
            [(rows[i][0], namespace, hashes[i], vectors[i].tobytes()) for i in missing])
        if use_cache:
            conn.commit()
    query_vector = _unit(np.frombuffer(_get_query_embedding(query, db_path, conn=conn), dtype=np.float32))
    similarities = {i: float(np.dot(vectors[i], query_vector)) for i in range(len(rows))}
    terms = set(re.findall(r'\w+', query.casefold().replace('_', ' ')))
    lexical = {i: sum(term in text.casefold().replace('_', ' ') for term in terms) for i, text in enumerate(texts)}
    lexical_order = sorted((i for i in lexical if lexical[i]), key=lambda i: -lexical[i])
    # Similarity is a retrieval cutoff, not calibrated confidence or tool permission.
    semantic_order = sorted((i for i in similarities if similarities[i] >= .35), key=lambda i: -similarities[i])
    scores = {}
    for route in (lexical_order, semantic_order):
        for rank, i in enumerate(route, 1):
            scores[i] = scores.get(i, 0.0) + 1 / (60 + rank)
    ordered = sorted(scores, key=lambda i: (-scores[i], -(rows[i][5] / rows[i][4] if rows[i][4] else 0), i))[:limit]
    result = []
    for i in ordered:
        name, cat, description, raw, calls, successes, latency = rows[i]
        params = json.loads(raw or '{}')
        result.append(dict(tool_name=name, category=cat, description=description,
            parameters=params.get('parameters', {}), examples=params.get('examples', []),
            score=scores[i], semantic_similarity=similarities[i], call_count=calls,
            reliability_pct=round(successes / calls * 100, 1) if calls else None,
            last_latency_ms=round(latency, 2) if calls else None))
    if use_cache and conn.execute('PRAGMA data_version').fetchone()[0] == key[0][2]:
        key = (_database_change_token(conn), namespace, query, category.casefold(), limit)
        with _RESULTS_LOCK:
            _RESULTS[key] = deepcopy(result)
            while len(_RESULTS) > 128:
                _RESULTS.popitem(last=False)
    return result
