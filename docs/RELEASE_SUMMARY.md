# ROMS 1.6 — precise citations and semantic tools

ROMS retains the pinned local **EmbeddingGemma 2 Q8** model and adds structure
to retrieval, stricter context budgets, and semantic tool discovery. Python and
Mojo MCP clients share the upgrades; portable task briefs carry the source data.

## Changes

- Page, section, table-column, slide/sheet and Python-symbol metadata survive
  passage splitting and atomic index replacement. Contextual embedding headers
  are separate from original extracted evidence.
- `get_source_context` expands a citation into bounded neighboring passages in
  the same section. Task briefs retain known locations alongside content hashes.
- Context budgets include formatted headers, escaped XML and separators. Tiny
  budgets no longer trigger an unconditional 50-token excerpt. Python callers
  can supply their consuming model's tokenizer.
- Tool discovery uses actual EmbeddingGemma 2 embeddings, with lexical/semantic
  rank fusion, category filtering and persistent content/model-aware caching.
  Unknown reliability and latency remain unknown.
- Configurable local Tesseract languages through `ROMS_OCR_LANGUAGES`.
- A self-contained retrieval evaluator builds temporary indexes, records source
  fingerprints and measures fixed synthetic/manual queries. A real-model smoke
  check exercises semantic tools, source expansion and context bounds.

## Upgrade and verification

Update the source and use the existing EmbeddingGemma 2 runtime. Re-ingest the
original documents (`reload_knowledge` for the managed folder) to populate source
locations and contextual embeddings. Existing 1.5 indexes remain readable;
missing metadata is not invented. Re-ingestion changes chunk IDs, so search
again before selecting evidence. Earlier embedding-model migrations retain
separate database identity protection.

Run `python scripts/verify_rag_upgrades.py`,
`python scripts/evaluate_single_search.py`, and
`python -m pytest tests scripts -q -ra` in the documented environment.
Optional live-model, voice, container-worker and desktop checks require their
separate runtimes. Passing the portable suite does not certify those deployments.

The second RAGStuff review included the added holographic-memory and Hindsight
sources. Their useful provenance, cache and budget patterns informed this work.
Hash-based VSA/HRR encoders, new database services, automatic memory capture,
heavy OCR stacks and extra reranking models were not added to the default runtime.
The changes are original ROMS code; reference repositories and user data are not
bundled. See [search details](search-upgrades.md) and
[reference-review scope](reference-review.md#ragstuff-review-for-16).

[Executed local checks and fixed-fixture comparison](verification/rag-upgrades.json)
record the tested source fingerprints and observed limits.
