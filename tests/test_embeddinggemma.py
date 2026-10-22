"""Offline contract checks; real-model acceptance uses verify_embeddinggemma.py."""
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from app.embeddinggemma import EmbeddingGemma, QUERY_PREFIX, DOCUMENT_PREFIX


def adapter():
    model = EmbeddingGemma.__new__(EmbeddingGemma)
    model.input_names = {'input_ids', 'attention_mask'}
    model.seen = []

    def tokenize(texts, **kwargs):
        model.seen.extend(texts)
        return {'input_ids': np.ones((len(texts), 10), dtype=np.int64),
                'attention_mask': np.ones((len(texts), 10), dtype=np.int64)}

    model.tokenizer = tokenize
    class Session:
        def run(self, names, inputs):
            assert names == ['sentence_embedding']
            assert len(inputs['input_ids']) <= 4
            return [np.ones((len(inputs['input_ids']), 768))]
    model.session = Session()
    return model


def test_prompts_normalization_batches_and_empty_input():
    model = adapter()
    query = model.encode('planet', query=True)
    docs = model.encode(['Mars'] * 9)
    assert model.seen == [QUERY_PREFIX + 'planet'] + [DOCUMENT_PREFIX + 'Mars'] * 9
    assert query.shape == (768,)
    assert docs.shape == (9, 768)
    np.testing.assert_allclose(np.linalg.norm(docs, axis=1), 1, atol=1e-6)
    assert model.encode([]).shape == (0, 768)


def test_rejects_overflow_and_invalid_vectors():
    model = adapter()
    model.tokenizer = lambda *a, **k: {'input_ids': np.ones((1, 2049))}
    with pytest.raises(ValueError, match='2048 tokens'):
        model.encode('too long')
    model = adapter()
    model.session.run = lambda *a: [np.full((1, 768), np.nan)]
    with pytest.raises(ValueError, match='finite'):
        model.encode('bad')
    model.session.run = lambda *a: [np.zeros((1, 768))]
    with pytest.raises(ValueError, match='zero vector'):
        model.encode('bad')


def test_gemma_config_and_existing_index_protection(tmp_path):
    code = '''
from app import config
from app.db import get_connection, init_database
assert config.EMBEDDING_DIM == 768
assert config.DB_PATH.name == 'embeddinggemma-q8.db'
conn = get_connection()
conn.execute('CREATE VIRTUAL TABLE vec_chunks USING vec0(embedding float[384])')
try:
    init_database()
except ValueError as exc:
    assert 'new database' in str(exc)
else:
    raise AssertionError('Accepted incompatible index')
assert conn.execute("SELECT sql FROM sqlite_master WHERE name='vec_chunks'").fetchone()[0].endswith('float[384])')
'''
    env = {**os.environ, 'ROMS_EMBEDDING_MODEL': 'embeddinggemma-q8', 'ROMS_DATA_DIR': str(tmp_path)}
    env.pop('ROMS_DB_PATH', None)
    result = subprocess.run([sys.executable, '-c', code], env=env,
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('setting,value', [
    ('ROMS_EMBEDDING_MODEL', 'sentence-transformers/all-MiniLM-L6-v2'),
    ('ROMS_EMBEDDING_PROVIDER', 'openai'),
])
def test_legacy_backends_fail_with_actionable_error(setting, value):
    env = {**os.environ, setting: value}
    result = subprocess.run([sys.executable, '-c', 'import app.config'], env=env,
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
    assert result.returncode != 0
    assert 'ROMS supports only' in result.stderr


def test_default_is_gemma_without_model_selector(tmp_path):
    env = {**os.environ, 'ROMS_DATA_DIR': str(tmp_path)}
    for name in ('ROMS_EMBEDDING_MODEL', 'ROMS_EMBEDDING_PROVIDER', 'ROMS_DB_PATH'):
        env.pop(name, None)
    result = subprocess.run([sys.executable, '-c', '''
from app import config
assert config.EMBEDDING_MODEL_NAME == 'embeddinggemma-q8'
assert config.EMBEDDING_DIM == 768
assert config.EMBEDDING_PROVIDER == 'local'
assert config.DB_PATH.name == 'embeddinggemma-q8.db'
'''], env=env, cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
