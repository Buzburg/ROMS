"""Actual SQLite retrieval plus controlled external/model boundary tests."""
import json
from pathlib import Path
import sqlite3
import struct
from types import SimpleNamespace

import numpy as np
import pytest
from app import zgsearch, rag_engine
from app.db import init_database, get_connection


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    path = tmp_path / 'search.db'
    init_database(path)
    conn = get_connection(path)
    documents = [('policy', 'policy', 'Return policy'), ('guide', 'guide', 'Technical guide')]
    conn.executemany('INSERT INTO okf_registry(doc_id,doc_type,title,source_path) VALUES (?,?,?,?)',
                     [(doc, kind, title, f'/docs/{doc}.md') for doc, kind, title in documents])
    rows = [(1, 'policy', 'damaged replacement refund'),
            (2, 'policy', 'damaged replacement refund'),
            (3, 'guide', 'network connection troubleshooting'),
            (4, 'guide', 'Überprüfung OR ERR_CONNECTION_REFUSED')]
    conn.executemany('INSERT INTO fts_chunks VALUES (?,?,?)', rows)
    conn.executemany('INSERT INTO vec_chunks(chunk_id,doc_id,content,embedding) VALUES (?,?,?,?)',
                     [(cid, doc, text, struct.pack('768f', *([float(cid)] * 768))) for cid, doc, text in rows])
    conn.execute("INSERT INTO chunk_topics VALUES (2, 'billing', 1)")
    conn.commit()
    monkeypatch.setattr(rag_engine, 'compute_embedding_vector', lambda query: [0.0] * 768)
    yield path, conn
    conn.close()


@pytest.mark.parametrize('query,doc', [('damagd replacment', 'policy'), ('repla', 'policy'),
                                      ('Überprüfung', 'guide'), ('OR', 'guide'), ('ERR_CONNECTION_REFUSED', 'guide')])
def test_indexed_fuzzy_and_literal_queries(corpus, query, doc):
    path, _ = corpus
    results = zgsearch.zg_search(query, db_path=path)
    assert results and results[0]['doc_id'] == doc
    assert results[0]['source_path'] == f'/docs/{doc}.md'




def test_duplicate_chunks_survive_and_routes_fuse(corpus):
    results = zgsearch.zg_search('refund', db_path=corpus[0])
    assert {item['chunk_id'] for item in results if item['doc_id'] == 'policy'} == {1, 2}
    assert results[0]['fuzzy_rank'] is not None and results[0]['vector_rank'] is not None


def test_strict_combined_filters(corpus):
    results = zgsearch.zg_search('refund', filters={'doc_type': 'policy', 'doc_id': 'policy', 'topic': 'billing'},
                                 db_path=corpus[0])
    assert [r['chunk_id'] for r in results] == [2]
    assert zgsearch.zg_search('refund', filters={'topic': 'missing'}, db_path=corpus[0]) == []


def test_vector_filter_before_top_k(corpus):
    path, conn = corpus
    for cid in range(5, 50):
        text = 'nearer irrelevant guide'
        conn.execute('INSERT INTO fts_chunks VALUES (?,?,?)', (cid, 'guide', text))
        conn.execute('INSERT INTO vec_chunks(chunk_id,doc_id,content,embedding) VALUES (?,?,?,?)',
                     (cid, 'guide', text, struct.pack('768f', *([0.0] * 768))))
    conn.commit()
    results = zgsearch.zg_search('anything', filters={'doc_type': 'policy'}, limit=1, db_path=path)
    assert len(results) == 1 and results[0]['doc_id'] == 'policy'


def test_typo_vocabulary_tracks_writes(corpus):
    path, conn = corpus
    assert all(hit['chunk_id'] != 99 for hit in zgsearch.zg_search('zephyrium', db_path=path))
    conn.execute("INSERT INTO fts_chunks VALUES (99,'policy','zephyrium')")
    assert zgsearch.zg_search('zephyrum', db_path=path)[0]['chunk_id'] == 99
    conn.execute('DELETE FROM fts_chunks WHERE chunk_id = 99')
    assert all(hit['chunk_id'] != 99 for hit in zgsearch.zg_search('zephyrum', db_path=path))


@pytest.mark.parametrize('kwargs', [{'limit': 0}, {'limit': -1}, {'limit': True}, {'limit': 101},
                                     {'mode': 'magic'}, {'filters': {'category': 'x'}}, {'backend': 'other'}])
def test_invalid_options_fail_before_database(monkeypatch, kwargs):
    monkeypatch.setattr(zgsearch, 'get_connection', lambda *a: pytest.fail('invalid input opened database'))
    with pytest.raises((ValueError, TypeError)):
        zgsearch.zg_search('hello', **kwargs)


def test_empty_punctuation_and_corrupt_index(corpus):
    path, conn = corpus
    assert zgsearch.zg_search('', db_path=path) == []
    assert zgsearch.zg_search('"***()', db_path=path) == []
    conn.execute('DROP TABLE fts_chunks')
    with pytest.raises(sqlite3.OperationalError):
        zgsearch.zg_search('refund', db_path=path)


def test_facets_and_tool_citations(corpus):
    from app.tools import zg_search_engine
    facets = zgsearch.get_zg_facets(corpus[0])
    assert facets['topics'] == {'billing': 1}
    text = zg_search_engine('refund', topic='billing', db_path=corpus[0])
    assert 'chunk_id=2' in text and '/docs/policy.md' in text


















def test_regex_plugin_global_limit_and_option_like_pattern(tmp_path):
    import asyncio
    from fastmcp import FastMCP
    from custom_tools.code_search import register_tools
    mcp = FastMCP('search-test')
    register_tools(mcp)
    assert asyncio.run(mcp.get_tool('search_indexed_codebase')) is None
    tool = asyncio.run(mcp.get_tool('search_codebase'))
    (tmp_path / 'a.txt').write_text('--needle\n--needle\n')
    (tmp_path / 'b.txt').write_text('--needle\n')
    output = tool.fn(pattern='--needle', target_dir=str(tmp_path), max_matches=2)
    assert len(output.splitlines()) == 2 and all('--needle' in line for line in output.splitlines())








def test_typo_expansion_uses_the_same_stemming_as_the_index(corpus):
    path, conn = corpus
    conn.execute("INSERT INTO fts_chunks VALUES (99, 'guide', 'authentication')")
    assert conn.in_transaction
    assert zgsearch.zg_search('authentcation', db_path=path)[0]['chunk_id'] == 99
    assert conn.in_transaction
    conn.rollback()
    assert conn.execute('SELECT count(*) FROM fts_chunks WHERE chunk_id=99').fetchone()[0] == 0
    assert all(hit['chunk_id'] != 99 for hit in zgsearch.zg_search('authentcation', db_path=path))








def test_auto_skips_typo_work_for_known_terms(corpus, monkeypatch):
    from types import SimpleNamespace
    native = zgsearch.kernels()
    monkeypatch.setattr(zgsearch, 'kernels', lambda: SimpleNamespace(
        fuse=native.fuse, expand=lambda *a: pytest.fail('known term scanned typo vocabulary')))
    hits = zgsearch.zg_search('replacement ERR_CONNECTION_REFUSED', db_path=corpus[0])
    assert hits and any(hit['fuzzy_rank'] for hit in hits)
    assert any(hit['vector_rank'] for hit in hits)


def test_auto_corrects_unknown_terms_and_keeps_source(corpus):
    hits = zgsearch.zg_search('damagd replacment', db_path=corpus[0], filters={'doc_type': 'policy'})
    assert hits and hits[0]['doc_id'] == 'policy'
    assert hits[0]['fuzzy_rank'] == 1
    assert hits[0]['source_path'] == '/docs/policy.md'








def test_adaptive_cache_reuses_results_without_retrieval(corpus, monkeypatch):
    path, conn = corpus
    # First call may persist an embedding, second can cache a stable snapshot.
    zgsearch.zg_search('refund', db_path=path)
    expected = zgsearch.zg_search('refund', db_path=path)
    monkeypatch.setattr(zgsearch, 'vector_search', lambda *a, **k: pytest.fail('cache missed'))
    got = zgsearch.zg_search('refund', db_path=path)
    assert got == expected
    got[0]['content'] = 'poison'
    assert zgsearch.zg_search('refund', db_path=path) == expected


def test_adaptive_cache_invalidates_metadata_and_other_writer(corpus):
    path, conn = corpus
    zgsearch.zg_search('refund', db_path=path)
    zgsearch.zg_search('refund', db_path=path)
    conn.execute("UPDATE okf_registry SET title='New title' WHERE doc_id='policy'")
    conn.commit()
    assert zgsearch.zg_search('refund', db_path=path)[0]['title'] == 'New title'
    other = get_connection(path, reuse=False)
    try:
        other.execute("UPDATE okf_registry SET title='Other writer' WHERE doc_id='policy'")
        other.commit()
        assert zgsearch.zg_search('refund', db_path=path)[0]['title'] == 'Other writer'
    finally:
        other.close()


def test_adaptive_cache_separates_filters_and_private_changes(corpus):
    path, conn = corpus
    for _ in range(2):
        zgsearch.zg_search('refund', db_path=path)
    hits = zgsearch.zg_search('refund', filters={'topic': 'billing'}, db_path=path)
    assert [hit['chunk_id'] for hit in hits] == [2]
    conn.execute("UPDATE okf_registry SET title='Private' WHERE doc_id='policy'")
    assert zgsearch.zg_search('uncached query', db_path=path)[0]['title'] == 'Private'
    assert conn.in_transaction  # embedding cache writes must not commit private edits
    conn.rollback()
    assert zgsearch.zg_search('refund', db_path=path)[0]['title'] != 'Private'


def test_knowledge_and_context_share_adaptive_path(corpus, monkeypatch):
    from app import rag_engine
    calls = []
    original = zgsearch.zg_search
    def search(*args, **kwargs):
        calls.append(kwargs)
        return original(*args, **kwargs)
    monkeypatch.setattr(zgsearch, 'zg_search', search)
    assert 'damaged replacement refund' in rag_engine.search_knowledge_base('replacment', db_path=corpus[0])
    assert 'damaged replacement refund' in rag_engine.search_grounded_context('replacment', db_path=corpus[0])
    assert len(calls) == 2 and all('backend' not in call for call in calls)


def test_research_queries_once_and_preserves_distinct_chunks(monkeypatch):
    from app import autoresearch
    calls = []
    prefix = 'A shared introduction ' * 4
    monkeypatch.setattr(autoresearch, 'detect_query_topics', lambda *a, **kw: [])
    monkeypatch.setattr(autoresearch, 'deconstruct_research_topic', lambda topic: [topic, topic])
    def search(query, **kwargs):
        calls.append(query)
        return [dict(chunk_id=i, doc_id='same', content=prefix + str(i), score=0.02) for i in (1, 2)]
    monkeypatch.setattr(autoresearch, 'local_search', search)
    result = autoresearch.execute_autoresearch('question', depth=2, save_to_knowledge=False)
    assert calls == ['question']
    assert len(result['sources']) == 2


def test_only_one_knowledge_search_is_registered():
    import asyncio
    from app.server import mcp
    tool = asyncio.run(mcp.get_tool('search_knowledge_base'))
    assert set(tool.parameters['properties']) == {'query', 'limit', 'doc_type', 'doc_id', 'topic'}
    assert asyncio.run(mcp.get_tool('zg_search')) is None
    assert asyncio.run(mcp.get_tool('search_by_topic')) is None


@pytest.mark.parametrize('option', ['mode', 'backend', 'rerank', 'fuzzy'])
def test_removed_engine_choices_are_rejected(option):
    with pytest.raises(TypeError):
        zgsearch.zg_search('query', **{option: True})


def test_mojo_is_required_even_if_old_python_option_is_set(monkeypatch):
    from app import search_native
    monkeypatch.setenv('ROMS_SEARCH_KERNEL', 'python')
    assert search_native.kernel_name() == 'mojo'
    monkeypatch.setattr(search_native, '_load', lambda: None)
    with pytest.raises(RuntimeError, match='required Mojo'):
        search_native.kernels()


def test_filtered_zg_search_batches_vector_result_metadata(monkeypatch):
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE VIRTUAL TABLE fts_chunks USING fts5(chunk_id UNINDEXED, doc_id UNINDEXED, content)")
    connection.execute("CREATE TABLE okf_registry (doc_id TEXT, doc_type TEXT, title TEXT, source_path TEXT)")
    connection.execute("INSERT INTO fts_chunks VALUES (1, 'candidate.md', 'unrelated candidate text')")
    connection.executemany(
        "INSERT INTO okf_registry (doc_id, doc_type, title) VALUES (?, ?, ?)",
        [("candidate.md", "policy", "Candidate"),
         ("allowed.md", "policy", "Allowed"),
         ("excluded.md", "guide", "Excluded")],
    )
    connection.commit()
    statements = []
    connection.set_trace_callback(statements.append)
    monkeypatch.setattr(zgsearch, "get_connection", lambda *args: connection)
    monkeypatch.setattr(zgsearch, "vector_search", lambda *args, **kwargs: [
        {"chunk_id": 10, "doc_id": "allowed.md", "content": "vector-only allowed", "distance": 0.1},
        {"chunk_id": 11, "doc_id": "excluded.md", "content": "vector-only excluded", "distance": 0.2},
        {"chunk_id": 12, "doc_id": "missing.md", "content": "vector-only missing registry", "distance": 0.3},
    ])

    results = zgsearch.zg_search("query", filters={"doc_type": "policy"}, limit=5)

    metadata_reads = [
        statement for statement in statements
        if "SELECT doc_id, doc_type, title, source_path FROM okf_registry WHERE doc_id IN" in statement
    ]
    assert len(metadata_reads) == 1
    assert [(item["doc_id"], item["title"], item["doc_type"]) for item in results] == [
        ("allowed.md", "Allowed", "policy"),
    ]
    connection.close()
