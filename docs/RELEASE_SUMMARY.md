# ROMS 1.5 — EmbeddingGemma 2 for every ROMS client

ROMS now uses **EmbeddingGemma 2 Q8** as its default local embedding model.
Search, ingestion, Python tools and the Mojo MCP entry point share the same
pinned model. It works with the existing assistant integrations and portable
briefs; no specific generation model, local project or paid embedding service
is required.

## Changes

- Public, pinned `onnx-community/embeddinggemma-2-ONNX` text inference on CPU,
  with normalized 768-dimensional query and document embeddings.
- Explicit empty image, video and audio feature inputs required by the new
  ONNX graph. ROMS continues to ingest extracted text with its existing passage
  limit; optional media encoders are not included.
- Updated minimum runtime requirements and Pixi lockfile for the new export.
- New default `data/embeddinggemma2-q8.db`, with model identity protection during
  initialization, ingestion and semantic search. Old 768-dimensional vectors
  cannot silently mix with the new embedding space.
- The previous `embeddinggemma-q8` configuration value remains an alias for
  the new model. Current setup docs and the service installer use the new name.

## Upgrade

Install the updated requirements, rebuild the Mojo modules, and run
`python scripts/fetch_embedding.py`. Use the new default database or set
`ROMS_DB_PATH` to a new file, then re-ingest the original documents. Old databases
are preserved; saved skills and operational records are not automatically moved.
See [migration and rollback instructions](search-upgrades.md#upgrading-from-embeddinggemma-300m).

The source distribution contains no private configuration, model weights,
precompiled machine-specific artifacts or user databases. Provisioning downloads
the public model into the standard Hugging Face cache; subsequent use can be offline.

See [verification and limits](verification/embeddinggemma2-release.md).
