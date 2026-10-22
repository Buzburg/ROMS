"""Provision the pinned EmbeddingGemma Q8 model for subsequent offline use."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    from app.config import get_embedding_model
    from app.embeddinggemma import MODEL_ID, REVISION
    get_embedding_model()
    print(f"Embedding model ready: {MODEL_ID}, revision {REVISION}")


if __name__ == "__main__":
    main()
