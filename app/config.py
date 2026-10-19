"""Configuration and centralized runtime resources for ROMS.

Optimized for local LLM inference co-location (zero GPU VRAM interference, CPU thread capping).
"""

import os
import threading
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("ROMS_DATA_DIR", str(BASE_DIR / "data")))
DB_PATH = Path(os.getenv("ROMS_DB_PATH", str(DATA_DIR / "roms.db")))
KNOWLEDGE_DIR = Path(os.getenv("ROMS_KNOWLEDGE_DIR", str(BASE_DIR / "knowledge")))
SKILLS_DIR = Path(os.getenv("ROMS_SKILLS_DIR", str(BASE_DIR / "skills")))
WORKSPACES_DIR = Path(os.getenv("ROMS_WORKSPACES_DIR", str(BASE_DIR / "workspaces")))
BASE_REPOS_DIR = Path(os.getenv("ROMS_REPOS_DIR", str(BASE_DIR / "repos")))

EMBEDDING_MODEL_NAME = os.getenv(
    "ROMS_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
)
EMBEDDING_DIM = 384

EMBEDDING_PROVIDER = os.getenv("ROMS_EMBEDDING_PROVIDER", "local").lower()
OLLAMA_BASE_URL = os.getenv("ROMS_OLLAMA_URL", "http://127.0.0.1:11434")
OPENAI_EMBED_URL = os.getenv("ROMS_OPENAI_EMBED_URL", "http://127.0.0.1:8000/v1/embeddings")

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
_torch_threads_configured = False
_model_lock = threading.Lock()


def get_embedding_model():
    with _model_lock:
        return _load_embedding_model()


def _load_embedding_model():
    """Centralized singleton loader for SentenceTransformer.

    Hard-pinned to CPU with thread capping to preserve 100% of GPU VRAM and CPU
    scheduling bandwidth for the co-located local LLM.
    """
    global _cached_model, _torch_threads_configured
    if _cached_model is None:
        import torch

        # Limit CPU threads to 2 so embeddings do not starve LLM inference threads
        if not _torch_threads_configured:
            torch.set_num_threads(2)
            if hasattr(torch, "set_num_interop_threads"):
                torch.set_num_interop_threads(1)
            _torch_threads_configured = True

        from sentence_transformers import SentenceTransformer

        # Force CPU device to completely avoid allocating CUDA VRAM
        _cached_model = SentenceTransformer(EMBEDDING_MODEL_NAME, device="cpu")
    return _cached_model


def compute_embedding_vector(text: str) -> list[float]:
    """Generates embedding vector with pluggable provider support (local CPU, Ollama, OpenAI)."""
    norm_text = text.strip()
    if EMBEDDING_PROVIDER == "ollama":
        import json
        import urllib.request
        req = urllib.request.Request(
            f"{OLLAMA_BASE_URL}/api/embeddings",
            data=json.dumps({"model": EMBEDDING_MODEL_NAME, "prompt": norm_text}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["embedding"]
    elif EMBEDDING_PROVIDER == "openai":
        import json
        import urllib.request
        req = urllib.request.Request(
            OPENAI_EMBED_URL,
            data=json.dumps({"input": norm_text, "model": EMBEDDING_MODEL_NAME}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["data"][0]["embedding"]
    else:
        # Default: CPU-pinned SentenceTransformer with gradient disabled
        import torch
        model = get_embedding_model()
        with torch.inference_mode():
            emb = model.encode(norm_text, output_value="sentence_embedding")
            return emb.tolist()
