"""One local Mojo search engine over SQLite BM25 and passage vectors."""
from collections import OrderedDict
import threading
import heapq
import sqlite3
from functools import lru_cache
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from app.db import get_connection
from app.search_native import kernels, kernel_name
from app.rag_engine import vector_search, _database_change_token, _embedding_namespace


# Small in-process result cache. Keys include connection identity, database writes,
# embedding space and every retrieval option; private transactions bypass it.
_SEARCH_CACHE = OrderedDict()
_CACHE_LOCK = threading.RLock()


def clear_search_cache():
    with _CACHE_LOCK:
        _SEARCH_CACHE.clear()


def _levenshtein_distance(s1: str, s2: str) -> int:
    """Computes Levenshtein edit distance between two tokens."""
    if len(s1) < len(s2):
        return _levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)

    previous_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def _top_lexical_candidates(
    candidates: List[Dict[str, Any]], count: int
) -> List[Dict[str, Any]]:
    """Select the same ranked prefix as a stable full sort, using bounded top-k work."""
    if 0 < count < len(candidates):
        return heapq.nlargest(count, candidates, key=lambda item: item["fuzzy_score"])
    return sorted(candidates, key=lambda item: item["fuzzy_score"], reverse=True)[:count]


def _fuzzy_token_match(query_token: str, target_token: str, max_distance: int = 2) -> Tuple[bool, float]:
    """Evaluates if target_token matches query_token within acceptable edit distance."""
    if query_token == target_token:
        return True, 1.0

    len_q = len(query_token)
    len_t = len(target_token)

    # Short tokens require exact prefix or max 1 distance
    if len_q <= 3:
        if target_token.startswith(query_token):
            return True, 0.9
        return False, 0.0

    allowed_dist = 1 if len_q <= 5 else max_distance
    if abs(len_q - len_t) > allowed_dist:
        if target_token.startswith(query_token):
            return True, 0.85
        return False, 0.0

    dist = _levenshtein_distance(query_token, target_token)
    if dist <= allowed_dist:
        score = 1.0 - (dist / max(len_q, len_t))
        return True, max(0.5, score)

    # Prefix match
    if target_token.startswith(query_token):
        return True, 0.85

    return False, 0.0


def _validate(query, limit, filters):
    if not isinstance(query, str) or len(query) > 4096:
        raise ValueError('query must be text of at most 4096 characters')
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError('limit must be an integer from 1 to 100')
    if set(filters) - {'doc_type', 'doc_id', 'topic'}:
        raise ValueError('Supported filters: doc_type, doc_id, topic')
    if any(not isinstance(value, str) or not value or len(value) > 4096 for value in filters.values()):
        raise ValueError('Filter values must be nonempty strings of at most 4096 characters')


def _filter_sql(filters):
    conditions, params = [], []
    for field in ('doc_type', 'doc_id'):
        if field in filters:
            conditions.append(f'r.{field} = ?')
            params.append(filters[field])
    if 'topic' in filters:
        conditions.append('EXISTS (SELECT 1 FROM chunk_topics ct WHERE ct.chunk_id = f.chunk_id AND ct.topic_id = ?)')
        params.append(filters['topic'])
    return (' AND ' + ' AND '.join(conditions) if conditions else ''), params


@lru_cache(maxsize=512)
def _stem_terms(tokens: tuple[str, ...]) -> tuple[str, ...]:
    """Use SQLite's own tokenizer; never approximate Porter or alter caller transactions."""
    tokenizer = sqlite3.connect(':memory:')
    try:
        tokenizer.execute("CREATE VIRTUAL TABLE terms USING fts5(token, tokenize='porter unicode61')")
        tokenizer.execute("CREATE VIRTUAL TABLE vocab USING fts5vocab(terms, 'instance')")
        tokenizer.executemany('INSERT INTO terms(token) VALUES (?)', [(token,) for token in tokens])
        stems = {}
        for doc, term in tokenizer.execute('SELECT doc, term FROM vocab ORDER BY doc, offset'):
            stems.setdefault(doc, []).append(term)
        # An identifier may become multiple FTS tokens; retain its original phrase.
        return tuple(stems[i][0] if len(stems.get(i, [])) == 1 else token
                     for i, token in enumerate(tokens, 1))
    finally:
        tokenizer.close()


def _fts_query(conn, query, fuzzy, *, adaptive=False):
    tokens = list(dict.fromkeys(re.findall(r'\w+', query.casefold())))
    if len(tokens) > 32 or any(len(token) > 128 for token in tokens):
        raise ValueError('Search supports at most 32 terms, each at most 128 characters')
    if not tokens:
        return ''
    if fuzzy:
        # TEMP vocabulary follows live FTS writes; no permanent migration or stale cache.
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS temp.roms_search_vocab USING fts5vocab(main, fts_chunks, 'row')")
    stems = _stem_terms(tuple(tokens)) if fuzzy else tokens
    groups = []
    for token, stem in zip(tokens, stems):
        terms = [f'"{token}"']
        # Known indexed terms need no edit-distance scan. This is evaluated against
        # the live index, so ingestion/deletion cannot leave a stale vocabulary cache.
        expand = fuzzy and (not adaptive or conn.execute(
            'SELECT 1 FROM fts_chunks WHERE fts_chunks MATCH ? LIMIT 1',
            (f'"{token}"',)).fetchone() is None)
        if expand:
            terms.append(f'"{token}"*')
            if len(stem) > 3:
                distance = 1 if len(stem) <= 5 else 2
                # Work is bounded per query. Restrict to indexed vocabulary, never passages.
                rows = conn.execute('SELECT term FROM temp.roms_search_vocab WHERE length(term) BETWEEN ? AND ? ORDER BY doc DESC, term LIMIT 2048',
                                    (len(stem) - distance, len(stem) + distance))
                vocabulary = [row[0] for row in rows]
                alternatives = [vocabulary[i] for i in kernels().expand(stem, vocabulary)]
                terms.extend('"' + term.replace('"', '""') + '"' for term in alternatives)
        groups.append('(' + ' OR '.join(terms) + ')')
    return ' OR '.join(groups)


def _metadata(conn, doc_ids):
    result = {}
    ids = list(dict.fromkeys(doc_ids))
    for start in range(0, len(ids), 500):
        batch = ids[start:start + 500]
        rows = conn.execute('SELECT doc_id, doc_type, title, source_path FROM okf_registry WHERE doc_id IN ('
                            + ','.join('?' for _ in batch) + ')', batch)
        result.update({doc_id: {'doc_type': kind, 'title': title, 'source_path': path}
                       for doc_id, kind, title, path in rows})
    return result


def zg_search(query: str, filters=None, limit: int = 5,
              db_path: Path | str | None = None) -> List[Dict[str, Any]]:
    """The single local engine: adaptive lexical retrieval plus semantic RRF in Mojo."""
    filters = dict(filters or {})
    _validate(query, limit, filters)
    native = kernels()
    from app import config
    if config.EMBEDDING_PROVIDER != "local":
        raise ValueError("ROMS search requires local embeddings")
    if not query.strip():
        return []
    candidate_limit = min(300, max(20, limit * 3))
    conn = get_connection(db_path)
    cache_key = None
    if not conn.in_transaction:
        change_token = _database_change_token(conn)
        cache_key = (change_token, _embedding_namespace(), query, tuple(sorted(filters.items())), limit)
        with _CACHE_LOCK:
            cached = _SEARCH_CACHE.get(cache_key)
            if cached is not None:
                _SEARCH_CACHE.move_to_end(cache_key)
                return [dict(item) for item in cached]
    where, params = _filter_sql(filters)
    expression = _fts_query(conn, query, True, adaptive=True)
    if not expression:
        return []
    rows = conn.execute('SELECT f.chunk_id, f.doc_id, f.content, bm25(fts_chunks) '
                        'FROM fts_chunks f JOIN okf_registry r ON f.doc_id = r.doc_id '
                        'WHERE fts_chunks MATCH ?' + where + ' ORDER BY bm25(fts_chunks), f.chunk_id LIMIT ?',
                        [expression, *params, candidate_limit])
    lexical = [dict(chunk_id=cid, doc_id=did, content=text, bm25_score=score)
               for cid, did, text, score in rows]
    kwargs = {}
    if filters:
        ids = [row[0] for row in conn.execute('SELECT f.chunk_id FROM fts_chunks f JOIN okf_registry r '
                                             'ON f.doc_id = r.doc_id WHERE 1=1' + where, params)]
        kwargs['chunk_ids'] = ids
    vectors = vector_search(query, limit=candidate_limit, db_path=db_path, conn=conn, **kwargs)
    metadata = _metadata(conn, [item['doc_id'] for item in lexical + vectors])
    identities, items, routes = {}, [], []
    for candidates in (lexical, vectors):
        route = []
        for item in candidates:
            meta = metadata.get(item['doc_id'])
            if meta is None or any(meta.get(key) != value for key, value in filters.items() if key == 'doc_type'):
                route.append(-1)
                continue
            key = (item['doc_id'], item['chunk_id'])
            if key not in identities:
                identities[key] = len(items)
                items.append({**item, **meta, 'backend': 'local-mojo'})
            route.append(identities[key])
        routes.append(route)
    ranked = native.fuse(routes[0], routes[1], limit)
    results = [dict(items[key], score=score, fuzzy_rank=lex_rank or None,
                    vector_rank=vec_rank or None)
               for key, score, lex_rank, vec_rank in ranked]
    if (cache_key is not None and not conn.in_transaction
            and _database_change_token(conn) == change_token
            and sum(len(value) for item in results for value in item.values()
                    if isinstance(value, str)) <= 65536):
        with _CACHE_LOCK:
            _SEARCH_CACHE[cache_key] = [dict(item) for item in results]
            _SEARCH_CACHE.move_to_end(cache_key)
            while len(_SEARCH_CACHE) > 64:
                _SEARCH_CACHE.popitem(last=False)
    return results


def get_zg_facets(db_path: Path | str | None = None) -> Dict[str, Any]:
    conn = get_connection(db_path)
    return {
        'document_types': dict(conn.execute('SELECT doc_type, count(*) FROM okf_registry GROUP BY doc_type')),
        'topics': dict(conn.execute('SELECT topic_id, count(DISTINCT chunk_id) FROM chunk_topics GROUP BY topic_id')),
        'total_chunks': conn.execute('SELECT count(*) FROM fts_chunks').fetchone()[0],
        'search_engine': 'ZG-Search (SQLite BM25 + vector RRF)',
        'kernel': kernel_name(),
    }
