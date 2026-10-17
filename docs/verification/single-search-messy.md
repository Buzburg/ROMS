# ROMS search: measured results and limits

Verified locally on 17 October 2026 with Python 3.12.14, Mojo 1.1.0 and the local
CPU embedding model. The required Mojo extension was compiled and exercised,
including through the compiled Mojo search entry point. The full application is
not a pure-Mojo implementation: document parsers, model inference and transport
use Python adapters; indexing uses native SQLite libraries.

## Retrieval measurements

| Exercise | Intended document first | Within top five | Fresh-query median | Cached median |
|---|---:|---:|---:|---:|
| Frozen 24-document, 459-passage corpus; 20 queries | 17/20 | 20/20 | 7.70 ms | 0.0265 ms |
| 14 synthetic messy files; 12 predeclared queries | 12/12 | 12/12 | 5.72 ms | 0.0227 ms |

These are small, manually labeled exercises, not production guarantees. Timings
exclude initial model loading. Fresh calls recomputed query embeddings; cached
calls reused populated results. The final measurement overlapped regression
execution, so scheduling noise is possible. Large-corpus throughput, arbitrary
handwriting and real-user relevance remain unmeasured.

The [per-query results](single-search-evaluation.json) preserve the measured
rankings and file hashes. The [native build record](local-search-mojo-artifact.json)
identifies the compiler, native sources and local binary used. Binaries and model
weights are not distributed in this source repository.

## What was exercised

- 679 regression tests passed; two unrelated live-model checks were skipped.
- 31 focused intake tests passed: actual Office/PDF/image extraction, English OCR,
  mixed encodings, malformed records, transaction rollback and nested-file dispatch.
- Six additional real-model integration tests passed for ingestion, retrieval,
  topics, caching and research-report collection.
- Actual OCR recovered text from images, multi-frame TIFF, scanned PDFs and images
  embedded in Word documents. Inputs remained unchanged.
- Long subword, CJK and Unicode passages were checked against the actual model
  tokenizer window before inference.
- Source identity, exact filters, cache invalidation and the required compiled
  kernels were checked. Local-only search rejects external embedding providers.

The full `verify_all.py --offline` command remained incomplete because the separate
native broker binary was absent. Passing search tests does not certify the broker,
installed services, operating-system integrations or a complete deployment.

## Reproduce

Install the dependencies in `requirements-dev.txt`, Mojo 1.1.0, Tesseract with English
language data and Poppler, then run:

```sh
python scripts/build_search_native.py
python -m pytest tests/test_search_native.py tests/test_search_upgrades.py tests/test_retrieval_quality.py tests/test_messy_ingestion.py tests/test_ingestion_quality.py tests/test_document_identity.py tests/test_source_library.py -q
```

The checked-in fixture generator creates Office files and images for real local
extraction tests; no remote model or OCR endpoint is needed for this suite.
The separate `scripts/evaluate_single_search.py` measurement requires locally
provisioned model files and the original frozen evaluation index under
`scratch/search-evaluation/`. Those local assets are not part of the download;
the report records historical fixture results, not a benchmark a fresh checkout
can run without preparing those assets.

OCR currently uses English. Legacy binary Office formats, encrypted documents,
archives and audio/video are unsupported. Failed updates retain their previous
index with a visible diagnostic. Deleting a knowledge file does not yet remove
its indexed snapshot. See the [search guide](../search-upgrades.md) for supported
formats, size limits and setup.
