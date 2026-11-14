"""Discovery uses real embedding contracts; cache and filter behavior is offline."""
import numpy as np
import pytest

from app import config, tool_embeddings, tool_rag
from app.db import get_connection, init_database


class Model:
    def __init__(self):
        self.calls = []

    def encode(self, texts, **kwargs):
        self.calls.append(list(texts))
        result = np.zeros((len(texts), config.EMBEDDING_DIM), dtype=np.float32)
        for i, text in enumerate(texts):
            result[i, 0 if 'Reset a user password' in text else 1] = 1
        return result


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    database = tmp_path / 'tools.db'
    init_database(database)
    model = Model()
    monkeypatch.setattr(config, 'get_embedding_model', lambda: model)
    monkeypatch.setattr(config, 'compute_embedding_vector', lambda text: [1.] + [0.] * (config.EMBEDDING_DIM - 1))
    from app import rag_engine
    monkeypatch.setattr(rag_engine, 'compute_embedding_vector', config.compute_embedding_vector)
    tool_rag.register_tool('reset_password', 'Reset a user password', 'accounts', examples=['Recover account access'], db_path=database)
    tool_rag.register_tool('forecast', 'Fetch tomorrow weather', 'weather', db_path=database)
    return database, model


def test_semantic_paraphrase_and_honest_unknown_reliability(catalog):
    database, _ = catalog
    result = tool_rag.search_tools('recover login access', db_path=database)
    assert result[0]['tool_name'] == 'reset_password'
    assert result[0]['semantic_similarity'] == 1
    assert result[0]['reliability_pct'] is None
    assert tool_rag.search_tools('recover login access', category='weather', db_path=database) == []
    assert tool_rag.search_tools('recover login access', category='absent', db_path=database) == []


def test_persistent_embeddings_and_mutation_safe_results(catalog):
    database, model = catalog
    first = tool_rag.search_tools('login recovery', db_path=database)
    first[0]['examples'].append('caller mutation')
    assert 'caller mutation' not in tool_rag.search_tools('login recovery', db_path=database)[0]['examples']
    tool_rag.clear_tool_cache()
    tool_rag.search_tools('another login query', db_path=database)
    assert len(model.calls) == 1
    tool_rag.register_tool('reset_password', 'Fetch weather forecast', 'accounts', db_path=database)
    assert tool_rag.search_tools('login recovery', db_path=database) == []
    assert len(model.calls) == 2


def test_external_disable_and_corrupt_cache_are_not_reused(catalog):
    database, model = catalog
    assert tool_rag.search_tools('login', db_path=database)
    writer = get_connection(database, reuse=False)
    with writer:
        writer.execute("UPDATE tool_embeddings SET vector=? WHERE tool_name='reset_password'", (b'bad',))
    tool_rag.search_tools('login', db_path=database)
    assert len(model.calls) == 2
    with writer:
        writer.execute("UPDATE tool_registry SET is_active=0 WHERE tool_name='reset_password'")
    assert tool_rag.search_tools('login', db_path=database) == []
    writer.close()


def test_model_identity_change_rebuilds_tool_vectors(catalog, monkeypatch):
    database, model = catalog
    tool_rag.search_tools('login', db_path=database)
    monkeypatch.setattr(tool_embeddings, 'identity', lambda: 'different verified model configuration')
    tool_rag.search_tools('login', db_path=database)
    assert len(model.calls) == 2


def test_read_does_not_commit_caller_transaction(catalog):
    database, _ = catalog
    conn = get_connection(database)
    conn.execute("UPDATE tool_registry SET description='password changed privately' WHERE tool_name='reset_password'")
    tool_rag.search_tools('login', db_path=database)
    assert conn.in_transaction
    conn.rollback()
    assert conn.execute("SELECT description FROM tool_registry WHERE tool_name='reset_password'").fetchone()[0] == 'Reset a user password'


def test_parallel_lookup_and_cache_invalidation(catalog):
    from concurrent.futures import ThreadPoolExecutor
    database, _ = catalog
    tool_rag.search_tools('login', db_path=database)  # Populate persistent vectors first.
    def query_many():
        try:
            for _ in range(30):
                assert tool_rag.search_tools('login', db_path=database)[0]['tool_name'] == 'reset_password'
        finally:
            get_connection(database).close()
    def clear_many():
        for _ in range(300):
            tool_rag.clear_tool_cache()
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(query_many) for _ in range(3)] + [pool.submit(clear_many)]
        for future in futures:
            future.result()
