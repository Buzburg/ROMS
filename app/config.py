"""Configuration and centralized runtime resources for ROMS.

Optimized for local LLM inference co-location (zero GPU VRAM interference, CPU thread capping).
"""

import os
import threading
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("ROMS_DATA_DIR", str(BASE_DIR / "data")))
DB_PATH = Path(os.getenv("ROMS_DB_PATH", str(DATA_DIR / "roms.db")))
KNOWLEDGE_DIR = Path(os.getenv("ROMS_KNOWLEDGE_DIR", str(BASE_DIR / "knowledge")))
SKILLS_DIR = Path(os.getenv("ROMS_SKILLS_DIR", str(BASE_DIR / "skills")))
WORKSPACES_DIR = Path(os.getenv("ROMS_WORKSPACES_DIR", str(BASE_DIR / "workspaces")))
BASE_REPOS_DIR = Path(os.getenv("ROMS_REPOS_DIR", str(BASE_DIR / "repos")))

# One pinned local embedding space; legacy indexes are never reused by default.
EMBEDDING_MODEL_NAME = "embeddinggemma-q8"
EMBEDDING_DIM = 768
EMBEDDING_PROVIDER = "local"
DB_PATH = Path(os.getenv("ROMS_DB_PATH", str(DATA_DIR / "embeddinggemma-q8.db")))
if os.getenv("ROMS_EMBEDDING_MODEL", EMBEDDING_MODEL_NAME) != EMBEDDING_MODEL_NAME:
    raise ValueError("ROMS supports only embeddinggemma-q8; remove the old ROMS_EMBEDDING_MODEL setting")
if os.getenv("ROMS_EMBEDDING_PROVIDER", "local").lower() != "local":
    raise ValueError("ROMS supports only local EmbeddingGemma Q8 embeddings")

# Local LLM Context & Hardware Controls
MAX_CONCURRENT_TASKS = int(os.getenv("ROMS_MAX_CONCURRENT", "2"))
MAX_CPU_PERCENT = float(os.getenv("ROMS_MAX_CPU_PERCENT", "85.0"))
MIN_AVAILABLE_RAM_MB = float(os.getenv("ROMS_MIN_RAM_MB", "2048.0"))
TOOL_EXECUTION_TIMEOUT = float(os.getenv("ROMS_TOOL_TIMEOUT", "120.0"))
MAX_RAG_CONTEXT_CHARS = int(os.getenv("ROMS_MAX_RAG_CHARS", "2000"))
MAX_RAG_CONTEXT_TOKENS = int(os.getenv("ROMS_MAX_RAG_TOKENS", "512"))
MIN_RELEVANCE_SCORE = float(os.getenv("ROMS_MIN_RELEVANCE_SCORE", "0.012"))

# Gateway / Proxy Configuration
ROMS_GATEWAY_PORT = int(os.getenv("ROMS_GATEWAY_PORT", "8844"))
ROMS_UPSTREAM_LLM_URL = os.getenv("ROMS_UPSTREAM_LLM_URL", "http://127.0.0.1:11434/v1")

_cached_model = None
_model_lock = threading.Lock()


def get_embedding_model():
    with _model_lock:
        return _load_embedding_model()


def _load_embedding_model():
    """Load the pinned CPU model once; failed loads remain retryable."""
    global _cached_model
    if _cached_model is None:
        from app.embeddinggemma import EmbeddingGemma
        _cached_model = EmbeddingGemma()
    return _cached_model


def compute_embedding_vector(text: str) -> list[float]:
    """Encode a search query with the pinned local Q8 model's query prompt."""
    return get_embedding_model().encode(text.strip(), query=True).tolist()
