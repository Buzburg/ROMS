# Quantized EmbeddingGemma verification

Scope: optional local CPU embedding backend, query/document prompts, token-window
handling, 768-dimensional storage and retrieval, and MiniLM compatibility.

Base revision: `b37b56e`; implementation is in the same commit as this record.
Working directory: `/home/aeon/Projects/ROMS`.
Environment: Linux, Python 3.12.14 in `.venv`, ONNX Runtime 1.31.0,
Transformers 5.20.2, existing compiled Mojo search and broker artifacts.
Model: `onnx-community/embeddinggemma-300m-ONNX`, revision
`5090578d9565bb06545b4552f76e6bc2c93e4a66`, `model_quantized.onnx` and its external weights.

Checks completed:

- `.venv/bin/python -m pytest tests/test_embeddinggemma.py tests/test_embedding_retry.py -q`:
  4 passed. Prompt roles, normalization, bounded batches, overflow/invalid-vector
  rejection, separate default database, incompatible-index rejection and loader retry.
- `HF_HUB_DISABLE_IMPLICIT_TOKEN=1 .venv/bin/python scripts/verify_embeddinggemma.py`:
  exit 0 using real quantized weights. Three queries ranked the correct document
  first; actual ingestion and vector/hybrid search agreed. Long Unicode text split
  into valid passages and encoded successfully; repeated ingestion was a no-op.
- `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/python scripts/verify_embeddinggemma.py`:
  exit 0 with the same real-model acceptance checks and no network provisioning.
- `.venv/bin/python -m pip check`: no broken requirements.
- `.venv/bin/python -I -S -B scripts/demo_first_run.py` and
  `HF_HUB_OFFLINE=1 .venv/bin/python -B scripts/demo_harness.py`: both exited 0.

Setup diagnostics: the first CLI provisioning attempt omitted the ONNX files due
to option parsing; provisioning through the adapter resolved it. ONNX Runtime 1.31
rejected external weights reached through Hub blob symlinks; provisioning now uses
real files in a revision-specific Hub local directory. The successful offline run
verifies that fix. An initial broad suite was interrupted after native broker
failures with missing Python runtime configuration; it is not passing evidence.
The subsequent suite uses the explicit runtime environment from the CI workflow.

The semantic fixture is small and synthetic. These checks establish integration
behavior, not comparative model quality or production throughput. Model weights
are downloaded separately and are not included in the Git repository.

Final broad checks:

- `.venv/bin/python -m pytest -q`: exit 0; **1131 passed, 79 skipped,
  49 subtests passed**, 9 warnings, 102.82 seconds. Skipped tests remain unverified.
- `.venv/bin/python tests/test_mojo_protocol.py "$PWD/build/roms-mcp" "$PWD"`:
  exit 0; native search, context bounds, memory/ticket lifecycle, resources, prompts,
  invalid-limit rejection and startup-failure behavior passed.

Both commands used `HF_HUB_OFFLINE=1`, `ROMS_PYTHON_PREFIX=$PWD/.venv`,
`PYTHONPATH=$PWD:$PWD/.venv/lib/python3.12/site-packages`, and
`MOJO_PYTHON_LIBRARY` pointing to this interpreter's `libpython3.12.so`.
The suite also used `TRANSFORMERS_OFFLINE=1`,
`OMARCHY_BROKER_BINARY=$PWD/build/omarchy-broker` and
`OMARCHY_SANDBOX_BINARY=$PWD/build/staging-sandbox`.
Raw local diagnostics: `/tmp/roms-gemma-suite-final.log`,
`/tmp/roms-gemma-protocol.log`, `/tmp/roms-gemma-offline.log`.
