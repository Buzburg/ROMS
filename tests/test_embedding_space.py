"""Exercise model-generation protection with real SQLite and sqlite-vec."""
import json

import numpy as np
import pytest

from app.db import get_connection, init_database
from app.embedding_space import identity, require_compatible
from app.okf_loader import ingest_document_file
from app.rag_engine import vector_search


def test_new_index_identity_is_persistent_and_initialization_repeatable(tmp_path):
    path = tmp_path / 'new.db'
    init_database(path)
    init_database(path)
    conn = get_connection(path)
    require_compatible(conn)
    assert json.loads(conn.execute('SELECT identity FROM roms_embedding_space').fetchone()[0]) == json.loads(identity())
    conn.close()


@pytest.mark.parametrize('marked', [False, True])
def test_same_dimension_old_index_rejected_without_changing_data(tmp_path, marked):
    path = tmp_path / 'old.db'
    conn = get_connection(path)
    conn.execute('CREATE VIRTUAL TABLE vec_chunks USING vec0(embedding float[768])')
    vec = np.full(768, 0.25, dtype=np.float32).tobytes()
    conn.execute('INSERT INTO vec_chunks(embedding) VALUES (?)', (vec,))
    if marked:
        conn.execute('CREATE TABLE roms_embedding_space(id INTEGER PRIMARY KEY, identity TEXT)')
        old = json.loads(identity())
        old['model'] = 'onnx-community/embeddinggemma-300m-ONNX'
        conn.execute('INSERT INTO roms_embedding_space VALUES(1,?)', (json.dumps(old, sort_keys=True),))
    conn.commit()
    before = list(conn.execute('SELECT name,sql FROM sqlite_master ORDER BY name'))
    with pytest.raises(ValueError, match='new database'):
        init_database(path)
    assert list(conn.execute('SELECT name,sql FROM sqlite_master ORDER BY name')) == before
    assert conn.execute('SELECT embedding FROM vec_chunks').fetchone()[0] == vec
    # Direct APIs must also reject an old index when callers skip initialization.
    with pytest.raises(ValueError, match='new database'):
        vector_search('planet', conn=conn)
    source = tmp_path / 'planet.txt'
    source.write_text('Mars has a red surface.')
    with pytest.raises(ValueError, match='new database'):
        ingest_document_file(source, path)
    assert conn.execute('SELECT embedding FROM vec_chunks').fetchone()[0] == vec
    conn.close()


def test_changed_revision_is_rejected_even_with_same_model_and_dimensions(tmp_path, monkeypatch):
    path = tmp_path / 'new.db'
    init_database(path)
    from app import embeddinggemma
    monkeypatch.setattr(embeddinggemma, 'REVISION', 'different-revision')
    with pytest.raises(ValueError, match='model identity differs'):
        init_database(path)


def test_old_index_stays_usable_when_building_new_index(tmp_path):
    old_path, new_path = tmp_path / 'embeddinggemma-q8.db', tmp_path / 'embeddinggemma2-q8.db'
    old = get_connection(old_path)
    old.execute('CREATE TABLE preserved(content TEXT)')
    old.execute("INSERT INTO preserved VALUES ('old knowledge')")
    old.commit()
    before = old_path.read_bytes()
    init_database(new_path)
    assert old_path.read_bytes() == before
    assert old.execute('SELECT content FROM preserved').fetchone()[0] == 'old knowledge'
    old.close()
