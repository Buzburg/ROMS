"""Offline retrieval correctness and timing; no model, live database, or downloads."""
import json
import hashlib
import sqlite3
import statistics
import struct
import time
from unittest.mock import patch

import pytest
from app import rag_engine as rag, zgsearch


@pytest.fixture
def lexical_db():
    connection = make_lexical_db()
    yield connection
    connection.close()


def make_lexical_db():
    connection = sqlite3.connect(':memory:')
    connection.execute("CREATE VIRTUAL TABLE fts_chunks USING fts5(chunk_id UNINDEXED, doc_id UNINDEXED, content, tokenize='porter unicode61')")
    connection.executemany('INSERT INTO fts_chunks VALUES (?, ?, ?)', [
        (1, 'operator.md', 'OR'),
        (2, 'unicode.md', 'Überprüfung'),
        (3, 'identifier.md', 'ERR_CONNECTION_REFUSED'),
        (4, 'policy.md', 'refund within thirty days'),
    ])
    return connection


@pytest.fixture(autouse=True)
def isolate_result_cache():
    rag.clear_result_cache()
    rag._MEM_CACHE.clear()
    yield
    rag.clear_result_cache()
    rag._MEM_CACHE.clear()


@pytest.mark.parametrize('query,expected', [
    ('OR', 'operator.md'),
    ('Überprüfung', 'unicode.md'),
    ('ERR_CONNECTION_REFUSED', 'identifier.md'),
    ('refund', 'policy.md'),
])
def test_literal_keyword_retrieval(lexical_db, query, expected):
    results = rag.lexical_search(query, conn=lexical_db)
    assert results and results[0]['doc_id'] == expected


def test_duplicate_query_terms_do_not_expand_fts_expression():
    assert rag._sanitize_fts_query('refund refund refund') == rag._sanitize_fts_query('refund')



def test_zg_top_k_lexical_ranking_matches_stable_full_sort():
    candidates = [
        {"chunk_id": index, "fuzzy_score": float((index * 37) % 101)}
        for index in range(250)
    ]
    expected = sorted(candidates, key=lambda item: item["fuzzy_score"], reverse=True)[:17]

    assert zgsearch._top_lexical_candidates(candidates, 17) == expected
    assert zgsearch._top_lexical_candidates(candidates, -7) == sorted(
        candidates, key=lambda item: item["fuzzy_score"], reverse=True
    )[:-7]
    assert zgsearch._top_lexical_candidates(candidates, 0) == []


def run_zg_ranking_benchmark():
    """Compares stable top-k selection against full sorting on a fixed corpus."""
    candidates = [
        {"chunk_id": index, "fuzzy_score": float((index * 7919) % 100003)}
        for index in range(20000)
    ]
    expected = sorted(candidates, key=lambda item: item["fuzzy_score"], reverse=True)[:15]
    assert zgsearch._top_lexical_candidates(candidates, 15) == expected

    measurements = {"full_sort_ms": [], "top_k_ms": []}
    for _ in range(7):
        start = time.perf_counter_ns()
        for _ in range(30):
            result = sorted(candidates, key=lambda item: item["fuzzy_score"], reverse=True)[:15]
            assert result == expected
        measurements["full_sort_ms"].append((time.perf_counter_ns() - start) / 30 / 1_000_000)

        start = time.perf_counter_ns()
        for _ in range(30):
            result = zgsearch._top_lexical_candidates(candidates, 15)
            assert result == expected
        measurements["top_k_ms"].append((time.perf_counter_ns() - start) / 30 / 1_000_000)

    print(json.dumps({
        "benchmark": "zg-search-stable-ranking-20k-items-top-15",
        "full_sort_median_ms": statistics.median(measurements["full_sort_ms"]),
        "top_k_median_ms": statistics.median(measurements["top_k_ms"]),
        "full_sort_batches_ms": measurements["full_sort_ms"],
        "top_k_batches_ms": measurements["top_k_ms"],
    }, indent=2))


def test_fuzzy_match_skips_edit_distance_for_impossible_token_lengths(monkeypatch):
    calls = []

    def track_distance(*args):
        calls.append(args)
        return 999

    monkeypatch.setattr(zgsearch, '_levenshtein_distance', track_distance)
    matched, score = zgsearch._fuzzy_token_match('transaction', 'xtransactionality')

    assert (matched, score) == (False, 0.0)
    assert calls == []


def test_fuzzy_length_pruning_reduces_distance_work(monkeypatch):
    calls = []
    distance = zgsearch._levenshtein_distance

    def track_distance(*args):
        if args[0] == 'transaction':
            calls.append(args)
        return distance(*args)

    monkeypatch.setattr(zgsearch, '_levenshtein_distance', track_distance)
    targets = ['x' * length for length in range(1, 26) for _ in range(4)]

    for target in targets:
        zgsearch._fuzzy_token_match('transaction', target)

    # The former path ran edit distance for all 100 targets; only 20 can now
    # fall within the allowed two-character length delta.
    assert len(calls) == 20


@pytest.mark.parametrize('query,target,expected', [
    ('damage', 'damagd', (True, pytest.approx(5 / 6))),
    ('three', 'threefold', (True, 0.85)),
    ('api', 'apix', (True, 0.9)),
    ('api', 'xyz', (False, 0.0)),
    ('transaction', 'transactionality', (True, 0.85)),
])
def test_fuzzy_match_scores_remain_stable(query, target, expected):
    assert zgsearch._fuzzy_token_match(query, target) == expected


def test_ranking_constant_is_part_of_result_cache(monkeypatch):
    monkeypatch.setattr(rag, 'vector_search', lambda *a, **kw: [
        {'doc_id': 'one', 'content': 'passage', 'distance': 0.1},
    ])
    monkeypatch.setattr(rag, 'lexical_search', lambda *a, **kw: [])
    with sqlite3.connect(':memory:') as connection:
        monkeypatch.setattr(rag, 'get_connection', lambda *a: connection)
        first = rag.hybrid_search('fixture', k_constant=60)
        second = rag.hybrid_search('fixture', k_constant=1)
    assert first[0]['score'] == pytest.approx(1 / 61)
    assert second[0]['score'] == pytest.approx(1 / 2)


def test_explicit_connections_do_not_share_results(monkeypatch):
    monkeypatch.setattr(rag, 'vector_search', lambda *a, **kw: [])
    monkeypatch.setattr(rag, 'lexical_search', lambda *a, **kw: [
        {'doc_id': str(id(kw['conn'])), 'content': 'private passage', 'bm25_score': -1},
    ])
    with sqlite3.connect(':memory:') as first, sqlite3.connect(':memory:') as second:
        a = rag.hybrid_search('same query', conn=first)
        b = rag.hybrid_search('same query', conn=second)
        assert a[0]['doc_id'] != b[0]['doc_id']


def test_returned_results_cannot_poison_cache(monkeypatch):
    monkeypatch.setattr(rag, 'vector_search', lambda *a, **kw: [
        {'doc_id': 'one', 'content': 'original', 'distance': 0.1},
    ])
    monkeypatch.setattr(rag, 'lexical_search', lambda *a, **kw: [])
    with sqlite3.connect(':memory:') as connection:
        monkeypatch.setattr(rag, 'get_connection', lambda *a: connection)
        first = rag.hybrid_search('fixture')
        first[0]['content'] = 'changed'
        second = rag.hybrid_search('fixture')
    assert second[0]['content'] == 'original'


def test_fusion_key_cannot_collide_on_delimiters(monkeypatch):
    monkeypatch.setattr(rag, 'vector_search', lambda *a, **kw: [
        {'doc_id': 'a::b', 'content': 'c', 'distance': 0.1},
        {'doc_id': 'a', 'content': 'b::c', 'distance': 0.2},
    ])
    monkeypatch.setattr(rag, 'lexical_search', lambda *a, **kw: [])
    with sqlite3.connect(':memory:') as connection:
        results = rag.hybrid_search('fixture', conn=connection)
    assert len(results) == 2


def test_identical_passages_keep_distinct_chunk_provenance(monkeypatch):
    monkeypatch.setattr(rag, 'vector_search', lambda *a, **kw: [
        {'chunk_id': 10, 'doc_id': 'policy.md', 'content': 'Same approved wording', 'distance': 0.1},
        {'chunk_id': 11, 'doc_id': 'policy.md', 'content': 'Same approved wording', 'distance': 0.2},
    ])
    monkeypatch.setattr(rag, 'lexical_search', lambda *a, **kw: [
        {'chunk_id': 12, 'doc_id': 'other-policy.md', 'content': 'Same approved wording', 'bm25_score': -1},
    ])
    with sqlite3.connect(':memory:') as connection:
        results = rag.hybrid_search('fixture', conn=connection)
    assert len(results) == 3
    assert {result['chunk_id'] for result in results} == {10, 11, 12}


def test_same_chunk_fuses_across_retrievers(monkeypatch):
    monkeypatch.setattr(rag, 'vector_search', lambda *a, **kw: [
        {'chunk_id': 10, 'doc_id': 'policy.md', 'content': 'Approved text', 'distance': 0.1},
    ])
    monkeypatch.setattr(rag, 'lexical_search', lambda *a, **kw: [
        {'chunk_id': 10, 'doc_id': 'policy.md', 'content': 'Updated text', 'bm25_score': -1},
    ])
    with sqlite3.connect(':memory:') as connection:
        results = rag.hybrid_search('fixture', conn=connection)
    assert len(results) == 1
    assert results[0]['content'] == 'Approved text'
    assert results[0]['score'] == pytest.approx(2 / 61)


def test_lexical_search_surfaces_schema_and_io_errors(lexical_db):
    lexical_db.execute('DROP TABLE fts_chunks')
    with pytest.raises(sqlite3.OperationalError):
        rag.lexical_search('refund', conn=lexical_db)


def test_lexical_search_still_returns_empty_for_no_match(lexical_db):
    assert rag.lexical_search('missingterm', conn=lexical_db) == []


def test_fusion_rewards_agreement_without_merging_distinct_passages(monkeypatch):
    monkeypatch.setattr(rag, 'vector_search', lambda *a, **kw: [
        {'doc_id': 'shared.md', 'content': 'agreed evidence', 'distance': 0.1},
        {'doc_id': 'shared.md', 'content': 'other evidence', 'distance': 0.2},
    ])
    monkeypatch.setattr(rag, 'lexical_search', lambda *a, **kw: [
        {'doc_id': 'shared.md', 'content': 'agreed evidence', 'bm25_score': -1},
    ])
    with sqlite3.connect(':memory:') as connection:
        results = rag.hybrid_search('fixture', conn=connection)
    assert len(results) == 2
    assert results[0]['content'] == 'agreed evidence'
    assert results[0]['score'] == pytest.approx(2 / 61)


def test_hot_result_cache_avoids_retrieval(monkeypatch):
    calls = []

    def retrieve(*args, **kwargs):
        calls.append(1)
        return [{'doc_id': 'cached.md', 'content': 'evidence', 'distance': 0.1}]

    monkeypatch.setattr(rag, 'vector_search', retrieve)
    monkeypatch.setattr(rag, 'lexical_search', lambda *a, **kw: [])
    with sqlite3.connect(':memory:') as connection:
        monkeypatch.setattr(rag, 'get_connection', lambda *a: connection)
        assert rag.hybrid_search('fixture') == rag.hybrid_search('fixture')
    assert len(calls) == 1


@pytest.mark.parametrize('external', [False, True], ids=['local-write', 'external-write'])
def test_result_cache_refreshes_after_index_update(monkeypatch, tmp_path, external):
    path = tmp_path / 'index.db'
    reader = sqlite3.connect(path)
    writer = sqlite3.connect(path) if external else reader
    try:
        reader.execute('CREATE VIRTUAL TABLE fts_chunks USING fts5(chunk_id UNINDEXED, doc_id UNINDEXED, content)')
        reader.execute("INSERT INTO fts_chunks VALUES (1, 'policy.md', 'refund old policy')")
        reader.commit()
        monkeypatch.setattr(rag, 'get_connection', lambda *a: reader)
        monkeypatch.setattr(rag, 'vector_search', lambda *a, **kw: [])
        assert rag.hybrid_search('refund')[0]['content'] == 'refund old policy'
        writer.execute("UPDATE fts_chunks SET content = 'refund corrected policy'")
        writer.commit()
        assert rag.hybrid_search('refund')[0]['content'] == 'refund corrected policy'
        writer.execute('DELETE FROM fts_chunks')
        writer.commit()
        assert rag.hybrid_search('refund') == []
    finally:
        if external:
            writer.close()
        reader.close()


def test_result_cache_does_not_survive_connection_replacement(monkeypatch):
    first = make_lexical_db()
    second = make_lexical_db()
    try:
        second.execute("UPDATE fts_chunks SET content = 'refund replacement policy' WHERE doc_id = 'policy.md'")
        second.commit()
        first.commit()
        monkeypatch.setattr(rag, 'vector_search', lambda *a, **kw: [])
        monkeypatch.setattr(rag, 'get_connection', lambda *a: first)
        before = rag.hybrid_search('refund')
        monkeypatch.setattr(rag, 'get_connection', lambda *a: second)
        after = rag.hybrid_search('refund')
        assert before[0]['content'] != after[0]['content']
    finally:
        first.close()
        second.close()


def test_uncommitted_results_are_not_cached_after_rollback(monkeypatch):
    with make_lexical_db() as connection:
        connection.commit()
        monkeypatch.setattr(rag, 'get_connection', lambda *a: connection)
        monkeypatch.setattr(rag, 'vector_search', lambda *a, **kw: [])
        connection.execute("UPDATE fts_chunks SET content = 'refund uncommitted policy'")
        assert rag.hybrid_search('refund')[0]['content'] == 'refund uncommitted policy'
        connection.rollback()
        assert rag.hybrid_search('refund')[0]['content'] != 'refund uncommitted policy'


def test_database_change_during_retrieval_is_not_cached(monkeypatch):
    with make_lexical_db() as connection:
        connection.commit()
        monkeypatch.setattr(rag, 'get_connection', lambda *a: connection)
        calls = []

        def retrieve(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                connection.execute("UPDATE fts_chunks SET content = 'refund corrected policy'")
                connection.commit()
            return []

        monkeypatch.setattr(rag, 'vector_search', retrieve)
        rag.hybrid_search('refund')
        assert not rag._RESULT_CACHE
        assert rag.hybrid_search('refund')[0]['content'] == 'refund corrected policy'
        assert len(calls) == 2


def embedding_db():
    connection = sqlite3.connect(':memory:')
    connection.execute('CREATE TABLE embedding_cache(query_hash TEXT PRIMARY KEY, embedding_blob BLOB)')
    return connection


@pytest.mark.parametrize('setting,value', [
    ('EMBEDDING_MODEL_NAME', 'different-model'),
    ('EMBEDDING_PROVIDER', 'openai'),
])
def test_embedding_configuration_changes_recompute_query(monkeypatch, setting, value):
    from app import config
    calls = []

    def embed(query):
        calls.append(query)
        return [float(len(calls))] * config.EMBEDDING_DIM

    monkeypatch.setattr(rag, 'compute_embedding_vector', embed)
    with embedding_db() as connection:
        first = rag._get_query_embedding('fixture', conn=connection)
        monkeypatch.setattr(config, setting, value)
        second = rag._get_query_embedding('fixture', conn=connection)
    assert first != second
    assert len(calls) == 2


def test_explicit_embedding_connections_keep_their_own_vectors(monkeypatch):
    from app import config
    calls = []

    def embed(query):
        calls.append(query)
        return [float(len(calls))] * config.EMBEDDING_DIM

    monkeypatch.setattr(rag, 'compute_embedding_vector', embed)
    with embedding_db() as first, embedding_db() as second:
        a = rag._get_query_embedding('fixture', conn=first)
        b = rag._get_query_embedding('fixture', conn=second)
    assert a != b
    assert len(calls) == 2


@pytest.mark.parametrize('invalid', [[1.0], [[0.5] * 768], [float('nan')] * 768, [float('inf')] * 768], ids=['wrong-length', 'nested', 'nan', 'infinity'])
def test_invalid_provider_vectors_are_not_cached(monkeypatch, invalid):
    monkeypatch.setattr(rag, 'compute_embedding_vector', lambda query: invalid)
    with embedding_db() as connection:
        with pytest.raises(ValueError):
            rag._get_query_embedding('fixture', conn=connection)
        assert connection.execute('SELECT COUNT(*) FROM embedding_cache').fetchone()[0] == 0


@pytest.mark.parametrize('bad_blob', [b'bad', struct.pack('768f', *([float('nan')] * 768))], ids=['wrong-length', 'nan'])
def test_corrupt_persistent_embedding_is_recomputed(monkeypatch, bad_blob):
    monkeypatch.setattr(rag, 'compute_embedding_vector', lambda query: [0.5] * 768)
    with embedding_db() as connection:
        expected = rag._get_query_embedding('fixture', conn=connection)
        connection.execute('UPDATE embedding_cache SET embedding_blob = ?', (bad_blob,))
        rag._MEM_CACHE.clear()
        assert rag._get_query_embedding('fixture', conn=connection) == expected
        assert connection.execute('SELECT embedding_blob FROM embedding_cache').fetchone()[0] == expected


def test_result_cache_respects_embedding_configuration(monkeypatch):
    from app import config
    calls = []

    def retrieve(*args, **kwargs):
        calls.append(1)
        return [{'doc_id': str(len(calls)), 'content': 'evidence', 'distance': 0.1}]

    monkeypatch.setattr(rag, 'vector_search', retrieve)
    monkeypatch.setattr(rag, 'lexical_search', lambda *a, **kw: [])
    with sqlite3.connect(':memory:') as connection:
        monkeypatch.setattr(rag, 'get_connection', lambda *a: connection)
        first = rag.hybrid_search('fixture')
        monkeypatch.setattr(config, 'EMBEDDING_MODEL_NAME', 'different-model')
        second = rag.hybrid_search('fixture')
    assert first != second
    assert len(calls) == 2


def test_persistent_embedding_cache_avoids_repeat_computation(monkeypatch):
    calls = []

    def embed(query):
        calls.append(1)
        return [0.5] * 768

    monkeypatch.setattr(rag, 'compute_embedding_vector', embed)
    with embedding_db() as connection:
        assert rag._get_query_embedding('fixture', conn=connection) == rag._get_query_embedding('fixture', conn=connection)
    assert len(calls) == 1


def test_embedding_revision_changes_recompute_query(monkeypatch):
    from app import config
    from app import embeddinggemma
    calls = []

    def embed(query):
        calls.append(1)
        return [float(len(calls))] * 768

    monkeypatch.setattr(rag, 'compute_embedding_vector', embed)
    with embedding_db() as connection:
        first = rag._get_query_embedding('fixture', conn=connection)
        monkeypatch.setattr(embeddinggemma, 'REVISION', 'different-revision')
        assert rag._get_query_embedding('fixture', conn=connection) != first
    assert len(calls) == 2


def test_hot_embedding_memory_cache_avoids_sql(monkeypatch):
    calls = []

    def embed(query):
        calls.append(1)
        return [0.5] * 768

    monkeypatch.setattr(rag, 'compute_embedding_vector', embed)
    with embedding_db() as connection:
        monkeypatch.setattr(rag, 'get_connection', lambda *a: connection)
        first = rag._get_query_embedding('fixture')
        sql = []
        connection.set_trace_callback(sql.append)
        assert rag._get_query_embedding('fixture') == first
        assert not sql
    assert len(calls) == 1


def test_legacy_query_only_cache_is_not_trusted(monkeypatch):
    calls = []

    def embed(query):
        calls.append(1)
        return [0.5] * 768

    monkeypatch.setattr(rag, 'compute_embedding_vector', embed)
    legacy_hash = hashlib.sha256(b'fixture').hexdigest()
    with embedding_db() as connection:
        connection.execute('INSERT INTO embedding_cache VALUES (?, ?)',
                           (legacy_hash, struct.pack('768f', *([1.0] * 768))))
        result = rag._get_query_embedding('fixture', conn=connection)
        assert result == struct.pack('768f', *([0.5] * 768))
        assert connection.execute('SELECT COUNT(*) FROM embedding_cache').fetchone()[0] == 2
    assert len(calls) == 1


def run_benchmark():
    """Fixed synthetic passages isolate fusion; timings exclude inference and DB I/O."""
    vectors = [
        {'doc_id': f'doc-{i}', 'content': f'Passage {i}: ' + 'evidence ' * 2000,
         'distance': i / 100}
        for i in range(40)
    ]
    lexical = [dict(item, bm25_score=-1) for item in reversed(vectors)]
    batches = []
    with sqlite3.connect(':memory:') as connection, \
            patch.object(rag, 'vector_search', return_value=vectors), \
            patch.object(rag, 'lexical_search', return_value=lexical):
        for batch in range(7):
            elapsed = []
            for i in range(220):
                rag.clear_result_cache()
                start = time.perf_counter_ns()
                results = rag.hybrid_search('benchmark', limit=20, conn=connection)
                elapsed.append((time.perf_counter_ns() - start) / 1_000_000)
                assert len(results) == 20
            batches.append(statistics.median(elapsed[20:]))
    hot_batches = []
    with sqlite3.connect(':memory:') as connection, \
            patch.object(rag, 'get_connection', return_value=connection), \
            patch.object(rag, 'vector_search', return_value=vectors), \
            patch.object(rag, 'lexical_search', return_value=lexical):
        rag.clear_result_cache()
        rag.hybrid_search('hot benchmark', limit=20)
        for _ in range(7):
            elapsed = []
            for _ in range(220):
                start = time.perf_counter_ns()
                rag.hybrid_search('hot benchmark', limit=20)
                elapsed.append((time.perf_counter_ns() - start) / 1_000_000)
            hot_batches.append(statistics.median(elapsed[20:]))
    with make_lexical_db() as connection:
        cases = [('OR', 'operator.md'), ('Überprüfung', 'unicode.md'),
                 ('ERR_CONNECTION_REFUSED', 'identifier.md'), ('refund', 'policy.md')]
        correct = sum(bool(results) and results[0]['doc_id'] == expected
                      for query, expected in cases
                      for results in [rag.lexical_search(query, conn=connection)])
    print(json.dumps({'benchmark': 'cold-fusion-40x18k-characters',
                      'batch_median_ms': batches,
                      'median_ms': statistics.median(batches),
                      'hot_cache_batch_median_ms': hot_batches,
                      'hot_cache_median_ms': statistics.median(hot_batches),
                      'lexical_top1_correct': correct, 'lexical_cases': len(cases)}, indent=2))


if __name__ == '__main__':
    run_benchmark()
