"""Exercise first-load recovery with real PyTorch thread configuration."""
import os
from pathlib import Path
import subprocess
import sys


def test_embedding_model_can_retry_after_first_load_failure():
    code = """
import sys, types
from app import config
calls = []
model = object()
def load(*args, **kwargs):
    calls.append(1)
    if len(calls) == 1:
        raise OSError('temporary first-load failure')
    return model
sys.modules['sentence_transformers'] = types.SimpleNamespace(SentenceTransformer=load)
try:
    config.get_embedding_model()
except OSError:
    pass
else:
    raise AssertionError('First load should fail')
assert config.get_embedding_model() is model
assert config.get_embedding_model() is model
assert len(calls) == 2
"""
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, '-c', code], cwd=root,
                            env={**os.environ, 'PYTHONPATH': str(root)},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
