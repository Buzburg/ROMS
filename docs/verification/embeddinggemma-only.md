# EmbeddingGemma Q8 as the sole backend

Base: `e2ad27a`; implementation and this record are committed together.
Environment: `/home/aeon/Projects/ROMS`, Linux, `.venv` Python 3.12.14,
ONNX Runtime 1.31.0, Transformers 5.20.2, Mojo 1.1.0.

ROMS now uses the pinned local Q8 model without a model selector. The default
index is `data/embeddinggemma-q8.db` (768 dimensions). Old MiniLM databases are
preserved and must be rebuilt from source documents in the new index. Unsupported
model/provider overrides fail with an actionable error. Query cache identity
includes the pinned model revision. Core pip and Pixi dependencies include ONNX
Runtime; Sentence Transformers is removed. The Mojo configuration uses the same
model singleton, and its schema initializer delegates to Python's dimension guard.

Verification:

- `.venv/bin/python -m pytest -q`: **1134 passed, 79 skipped, 49 subtests passed**,
  9 warnings, exit 0 in 110.55 seconds. Skipped coverage remains unverified.
- `.venv/bin/mojo build app_mojo/main.mojo -I . -o build/roms-mcp`: exit 0.
- `.venv/bin/python scripts/verify_embeddinggemma.py` with
  `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`: exit 0. Real Q8 inference,
  normalization, three semantic rankings, Unicode passage splitting, ingestion,
  idempotence, vector search and hybrid search passed without selector overrides.
- `.venv/bin/python tests/test_mojo_protocol.py "$PWD/build/roms-mcp" "$PWD"`:
  exit 0; 768d native search fixture, memory/tickets, resources, prompts, invalid
  requests and startup failure handling passed.
- `HF_HUB_OFFLINE=1 .venv/bin/python scripts/fetch_embedding.py`: exit 0 using
  the already cached pinned model.
- First-run and harness demos: exit 0; `.venv/bin/python -m pip check`: no broken requirements.
- Pixi 0.82.1 `pixi lock`: exit 0, regenerated lockfile. A fresh Pixi environment
  installation was not tested; runtime tests used the existing virtual environment.

The suite used offline model settings, `ROMS_PYTHON_PREFIX=$PWD/.venv`,
`PYTHONPATH=$PWD:$PWD/.venv/lib/python3.12/site-packages`, the interpreter's
`MOJO_PYTHON_LIBRARY`, and the existing compiled broker/sandbox paths via
`OMARCHY_BROKER_BINARY` and `OMARCHY_SANDBOX_BINARY`. The protocol check used
that Python environment and the newly rebuilt server.

Raw local evidence: `/tmp/roms-gemma-only-suite.log`,
`/tmp/roms-gemma-only-real.log`, `/tmp/roms-gemma-only-protocol.log`,
`/tmp/roms-gemma-only-fetch.log`, `/tmp/roms-gemma-lock.log`.

A supplemental compiled Mojo probe also passed configuration (768 dimensions),
shared database schema and model singleton checks, using explicit `Python.none()`
arguments. Its initial no-argument form hit an existing compile-time Python default
argument limitation; the production protocol check does not use that path.
Evidence: `/tmp/roms-gemma-only-config.log`.
