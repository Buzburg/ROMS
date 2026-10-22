"""Pinned, quantized EmbeddingGemma inference on the local CPU."""
from pathlib import Path

import numpy as np

MODEL_ID = "onnx-community/embeddinggemma-300m-ONNX"
REVISION = "5090578d9565bb06545b4552f76e6bc2c93e4a66"
QUERY_PREFIX = "task: search result | query: "
DOCUMENT_PREFIX = "title: none | text: "


class EmbeddingGemma:
    """Small encode-compatible adapter; model files stay in the HF cache."""

    def __init__(self):
        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise RuntimeError(
                "EmbeddingGemma requires: pip install -r requirements.txt"
            ) from exc
        from huggingface_hub import snapshot_download, constants
        from transformers import AutoTokenizer

        root = Path(snapshot_download(
            MODEL_ID, revision=REVISION,
            # ONNX external tensors must be real sibling files, not Hub blob symlinks.
            local_dir=Path(constants.HF_HOME) / "roms-embeddinggemma" / REVISION,
            allow_patterns=["onnx/model_quantized.onnx*", "*token*", "config.json"],
        ))
        self.tokenizer = AutoTokenizer.from_pretrained(root, local_files_only=True)
        # Leave ample room for either prefix and boundary tokenization changes.
        self.max_seq_length = 2048 - 32
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(
            str(root / "onnx/model_quantized.onnx"), sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        self.input_names = {item.name for item in self.session.get_inputs()}

    def encode(self, sentences, output_value="sentence_embedding", batch_size=32,
               *, query=False):
        if output_value != "sentence_embedding":
            raise ValueError("Only sentence embeddings are supported")
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        single = isinstance(sentences, str)
        texts = [sentences] if single else list(sentences)
        prefix = QUERY_PREFIX if query else DOCUMENT_PREFIX
        vectors = []
        # Bound quadratic attention memory even for long document passages.
        for start in range(0, len(texts), min(batch_size, 4)):
            batch = texts[start:start + min(batch_size, 4)]
            inputs = self.tokenizer([prefix + text for text in batch], padding=True,
                                    truncation=False, return_tensors="np")
            if inputs["input_ids"].shape[1] > 2048:
                raise ValueError("EmbeddingGemma input exceeds 2048 tokens; split the text first")
            result = np.asarray(self.session.run(
                ["sentence_embedding"],
                {name: inputs[name] for name in self.input_names},
            )[0], dtype=np.float32)
            if result.shape != (len(batch), 768) or not np.isfinite(result).all():
                raise ValueError("Expected finite 768-dimensional EmbeddingGemma vectors")
            norms = np.linalg.norm(result, axis=1, keepdims=True)
            if np.any(norms == 0):
                raise ValueError("EmbeddingGemma returned a zero vector")
            vectors.append(result / norms)
        result = np.concatenate(vectors) if vectors else np.empty((0, 768), dtype=np.float32)
        return result[0] if single else result
