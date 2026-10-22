# One local ROMS search

Use `search_knowledge_base(query, limit=3, doc_type="", topic="", doc_id="")`.
Chat, grounded context, topic filtering, research and the Mojo entry point use the
same local index and engine. There are no backend, mode, fuzzy or reranker choices
on the live search API. Old calls supplying those options must be updated.

```python
from app.rag_engine import local_search
hits = local_search("damagd replacment", limit=5,
                    filters={"doc_type": "policy"})
```

The engine combines SQLite FTS5 keyword ranking with precomputed local EmbeddingGemma Q8
passage vectors, then fuses ranks in compiled Mojo. Known terms skip typo work;
unknown terms use bounded prefix and typo expansion. Exact document/type/topic
filters apply before candidate selection. Results include source paths and chunk
IDs. A bounded cache follows database changes; uncommitted transactions bypass it.
The semantic route can return approximate matches even when no literal term matches.

Reference projects are design inspiration, not install requirements or search
services. The [dependency guide](dependencies.md) maps the actual runtime packages
to the features that use them.

## Mojo and installation

Mojo implements Unicode typo scoring, alternative selection, rank fusion, top-k
selection, text cleanup and passage splitting. The compiled module is required;
there is no Python search-kernel fallback. SQLite and sqlite-vec are native
libraries. Python remains the adapter for document formats, SQL, MCP and the
SentenceTransformers/PyTorch embedding model. This is not a pure-Mojo model port.

```sh
pixi install
pixi run build-search
pixi run -e dev test-search
```

In an existing environment containing Mojo 1.1.0 and the dependencies in
`pixi.toml`, use `python scripts/build_search_native.py`. Restart ROMS after
rebuilding. The former `ROMS_SEARCH_KERNEL` selector is no longer used. The
embedding provider must be `local`; external provider settings are rejected by
search and ingestion. Provision EmbeddingGemma Q8 with
`python scripts/fetch_embedding.py` before offline use. Initial provisioning may
require a download; queries and document inference then run on this machine.

Tesseract with English language data and Poppler's `pdftoppm` provide local OCR.
Their packages and the Python extraction libraries are declared in `pixi.toml`.
Search uses the embedded local index and model. It does not require a separate
search server, cloud OCR or neural reranker.

## Messy documents

Place files under `knowledge/` (nested folders are supported), or use the local
source-library importer. Run `reload_knowledge` for an immediate scan; the watcher
processes new and edited files. Source imports retain independent namespaced
snapshots. Originals are not changed. The shared importer supports:

| Data | Handling |
|---|---|
| Text, logs, Markdown and source code | UTF-8/BOM, UTF-16/32 and Windows-1252 fallback; normalized line endings/control characters; short facts retained |
| Broken Markdown/JSON/JSONL | Preserve malformed records as searchable text and attach extraction notes |
| CSV/TSV | Delimiter detection, repeated column labels, extra fields retained, missing cells marked |
| HTML | Visible text extraction; script/style bodies excluded |
| PDF | Text layers plus local OCR on scanned/image-containing pages |
| DOCX, XLSX/XLSM, PPTX | Paragraphs, tables, cells, slide text/notes and embedded raster-image OCR; formulas/macros are not executed |
| ODT, ODS, ODP | Text from document XML plus embedded raster-image OCR |
| PNG, JPEG, TIFF, WebP, BMP | Local OCR, including multi-frame TIFF |

Mojo splits text at paragraph/whitespace boundaries with a hard passage bound.
The actual embedding tokenizer then checks and splits overlong passages with
small overlaps, preventing silent model truncation on dense Unicode text.
Document embeddings are computed in batches at ingestion, not rebuilt per query.
A checksum covering original bytes and parser/model identity avoids repeat
extraction and OCR for unchanged files. Metadata-only edits trigger reindexing.

`get_knowledge_ingestion_status` reports failed files and extraction notes;
`reload_knowledge` includes this status. A failed file in `knowledge/` does not
stop other files. Its previous index remains available until a successful update;
check failure status when freshness matters. The watcher retries failed updates
with exponential backoff (1, 2, 4, 8, 16, 32, then 60 seconds between attempts),
including failures from startup. A new file version bypasses the previous version's
retry delay; `reload_knowledge` also retries immediately.

After a complete directory scan, the watcher and `reload_knowledge` remove deleted
managed documents from the registry, keyword/vector indexes, topic memberships,
and navigation, then invalidate cached search results. Renames remove the old
identity and index the new one. Missing roots, failed/incomplete walks, and roots
replaced during reconciliation preserve the existing index. These checks cannot
identify every storage failure that presents as a successfully readable empty
folder; keep backups of important originals.

Only root-relative document IDs whose recorded source belongs to that directory
are reconciled. Independent browser/MCP queue imports and source-library snapshots
are retained. The source-library importer retains its transactional whole-import
rollback on failure. Removing a library source removes its index and extraction notes.

“All” covers these categories, not every possible encoding or file format.
Encrypted/password-protected files, legacy `.doc/.xls/.ppt`, archives, audio/video,
unsupported formats and unreadable scans produce explicit errors/status rather
than invented content. OCR currently uses English; handwriting, damaged layouts,
charts, equations and complex merged tables may lose information. Image content
without recognizable text is not semantically described.

Bounds: 32 MiB per file, 20,000 passages, 100 PDF pages/slides/image frames,
40 megapixels per OCR image, 64 MiB expanded Office archives and 8 million
extracted characters. External extraction commands have timeouts within a
120-second extraction budget; Python library calls are checked between units
of work, not forcibly interrupted. Knowledge scans admit at most 10,000 files;
source-library imports retain their 1,000-file/32 MiB total limit. Large sources
should be split. Hidden directories, symlinks and dependency/build directories
are excluded from knowledge scans.

## Design and verification

ROMS combines lexical matching, stored passage vectors, exact filters and rank
fusion in one local engine. Research queries reuse the same index and preserve
source identity. Batched ingestion and cached query results avoid repeated work.
The encoder processes token sequences with context; lines are not treated as
single tokens. The current model remains separate from the Mojo ranking kernels.

Current measurements and checks are recorded in
[single-search verification](verification/single-search-messy.md). The evaluation
script requires the local model and frozen evaluation assets described there.

## Quantized EmbeddingGemma

ROMS supports the public [ONNX-community EmbeddingGemma 300M conversion](https://huggingface.co/onnx-community/embeddinggemma-300m-ONNX)
with 8-bit weights, pinned to revision `5090578d9565bb06545b4552f76e6bc2c93e4a66`.
Inference runs locally with ONNX Runtime's CPU provider and two compute threads.
This is the only supported embedding backend. Install the core requirements:

```bash
python -m pip install -r requirements.txt
python -c 'from app.config import get_embedding_model; get_embedding_model()'
```

The first load downloads approximately 330 MB of model/tokenizer files into the
Hugging Face cache. Review the upstream [Gemma terms](https://ai.google.dev/gemma/terms).
No model weights are bundled in this repository. Once cached, set
`HF_HUB_OFFLINE=1` to run without network access. If your stored Hub login has
expired, public provisioning can use `HF_HUB_DISABLE_IMPLICIT_TOKEN=1`.

Start ROMS and ingest your knowledge files; no model selector is required.
This backend uses normalized 768-dimensional embeddings and the model's distinct
search-query and document prefixes. It defaults to `data/embeddinggemma-q8.db`
(or that filename under `ROMS_DATA_DIR`), keeping the existing MiniLM index intact.
If you override `ROMS_DB_PATH`, choose a fresh database and re-ingest everything;
an incompatible vector dimension is rejected before schema changes. Never reuse
an index built by a different model, even when dimensions happen to match.
Remove old model/provider environment overrides. Unsupported model names and
remote providers are rejected at startup. Re-ingest source files into the new
Gemma index; existing MiniLM indexes are not automatically converted.

Document passages are split using the actual tokenizer with room for prefixes.
Inputs still exceeding the 2048-token model window raise an error rather than
silently truncating. Long queries must be shortened. Inference batches are capped
at four passages to bound attention memory.

Run the real-model acceptance check (requires the compiled Mojo search module):

```bash
python scripts/verify_embeddinggemma.py
```

It checks embeddings, semantic ranking, long Unicode passages, document ingestion,
and vector/hybrid search in a disposable database. It does not modify your index.
