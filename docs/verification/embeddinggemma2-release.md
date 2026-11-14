# EmbeddingGemma 2 release verification

Scope: the public Buzburg/ROMS distribution, based on revision
`8cae79972666713a7b71c5c38db828ea4fe66f9e`. Verification date: November 14, 2026.
No user model paths, user databases or private project files are part of this
upgrade.

## Model and migration

The adapter pins `onnx-community/embeddinggemma-2-ONNX` at
`daa72c51243991dfcaf9f9137d2c573d8f7790c0`. The revision was checked against the
public Hugging Face API, then downloaded into a fresh task-local cache without
a login. Its actual ONNX signature requires int64 `input_ids` and
`attention_mask`, plus float32 `image_features`, `video_features` and
`audio_features` of shape `(N, 512)`. Text inference supplies empty modality
arrays. Output remains normalized float32 `(batch, 768)` vectors.

The database records model ID, revision, dimension and query/document prefixes.
Regression tests cover fresh/repeated initialization; rejection and preservation
of unmarked and explicitly marked old 768d indexes; changed revisions; direct
search and ingestion without initialization; retention of a separate old database;
and the legacy configuration alias selecting the new default database.

## Executed checks

- Fresh installation of `requirements-dev.txt` plus Mojo 1.1.0 in Python 3.12.14.
  `uv pip check`: all 108 installed packages compatible.
- `python scripts/build_search_native.py` and builds of `app_mojo/main.mojo`,
  `app_mojo/omarchy_broker.mojo`, and `app_mojo/staging_sandbox.mojo`: exit 0.
- `python scripts/fetch_embedding.py`: exit 0 with a fresh public model download.
- `python scripts/verify_embeddinggemma.py` with offline flags: exit 0. Actual
  CPU inference, normalized 768d vectors, three semantic query rankings, Unicode
  splitting, ingestion/idempotence, vector search and hybrid search passed.
- `python scripts/verify_knowledge_skills.py`: exit 0. Real embedding ingestion,
  cited drafts, retrieval, source variants, revision-specific feedback, portable
  Markdown, repeatable backfill and deleted-source removal passed.
- `python tests/test_mojo_protocol.py build/roms-mcp .`: exit 0. Compiled MCP
  handshake, native search, memory and ticket lifecycle, resources/prompts,
  invalid-limit rejection and startup-failure handling passed.
- `python -m pytest -q -ra --tb=short`: 1,222 passed, 79 skipped,
  49 subtests passed; exit 0. Nine existing fork warnings were reported.
- Minimum supported ONNX Runtime 1.31.1, Transformers 5.18.0 and Hub 1.31.0:
  actual model load and semantic ranking passed in a separate environment.
  The former minimum Transformers 4.56 failed on the tokenizer's list-valued
  `extra_special_tokens`; ONNX Runtime 1.22 failed on the quantized Gather
  operator's `bits` attribute. The requirements were raised on this evidence.
- `pixi lock` regenerated the lockfile; `pixi install --locked` succeeded in a
  fresh project environment. Actual offline embedding, ingestion and retrieval
  also passed using that Pixi environment.

Full-suite runtime: ONNX Runtime 1.32.0, Transformers 5.23.0, Hub 2.4.0,
NumPy 2.5.4, PyTorch 2.14.1+cpu, FastMCP 4.2.0 and Mojo 1.1.0. Tests use
isolated data/state directories, offline model flags, the freshly downloaded
cache, the built broker/sandbox binaries, and Python paths resolved from the
active virtual environment. Raw output, command/environment records and source
hashes are retained in the release preparation checkout under
`scratch/embeddinggemma2/`; those local artifacts are not in the source package.

## Limits

Execution was on Linux x86-64. The Windows/Linux offline CI matrix now includes
embedding and index migration contracts; remote CI has not been run for this
release preparation. The 79 skipped checks require optional installed generation
models, container/worker images, desktop access or voice services. They do not
establish coverage of those features. No independent agent review was run.

The upgrade keeps ROMS's existing extracted-text ingestion and 2,048-token
passage limit. It does not implement the optional native image, audio or video
encoders. A fresh database requires re-ingestion; old operational records and
saved skills are preserved in the original database rather than migrated.

After regenerating the Pixi lockfile, the next full run correctly rejected
the stale lockfile hash in `config/build-inputs.json` (1 failed, 1,221 passed).
The regenerated lock was reviewed and installed successfully, then its actual
SHA-256 was recorded in that manifest. No test assertion was changed.

Final full-suite rerun after the manifest correction: **1,222 passed, 79 skipped,
49 subtests passed**, exit 0 in 70.72 seconds. The source archive was extracted
into a separate directory, its native search module rebuilt there, and its actual
offline embedding/ingestion/vector/hybrid-search verification passed. The archive
was checked for path containment and exclusion of environments, databases, model
weights and native binaries. Only release documentation changed after those checks.
