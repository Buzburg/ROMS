# ROMS: your documents, your machine, one fast search

Your useful information rarely arrives neatly organized. It lives in notes,
spreadsheets, source files, PDFs and screenshots. ROMS brings those materials
into a local knowledge base that you—and your AI tools—can search in one place.

Ask in everyday language, search an exact identifier, or make a typo. ROMS
combines keyword and semantic retrieval, ranks the results with compiled Mojo
kernels, and keeps source references attached. Local OCR makes printed text in
scans and images searchable. Batch indexing and cached results reduce repeated
work after the first import.

The same knowledge is available through MCP, alongside project memory, reusable
skills and tools for preparing source-backed next steps. Start with the no-install
demo, then build the full Linux/WSL search server when you are ready to index your
own files.

## In this update

- One local knowledge-search API with exact document, type and topic filters.
- Required Mojo kernels for typo selection, rank fusion, text cleanup and passage
  splitting, alongside native local indexes.
- Mixed-encoding and malformed-data recovery, PDF/Office extraction and English OCR.
- Nested-folder intake, visible extraction failures and atomic index replacement.
- A clearer README, practical setup guide and tests that exercise real extraction.

In the recorded small-fixture tests, all 12 messy-document queries placed the
intended document first. Loaded-model median searches measured about 6–8 ms;
results depend on the corpus and machine. [See the evidence and limits](verification/single-search-messy.md).

ROMS is an active developer project. Python adapters still handle file formats,
model inference and MCP. The source download does not include model weights or a
prebuilt native module. OCR is approximate, and optional system integrations have
separate prerequisites.

[Download the source](https://github.com/Buzburg/ROMS/archive/refs/heads/main.zip)
or follow the [README quick start](../README.md#try-one-useful-thing-first).

## Local knowledge workspace

`python roms.py knowledge` opens one local interface for file/folder uploads,
pasted text, progress, retries and search. SQLite preserves import jobs across
restarts. Originals are retained, and section headings plus explicit definitions
become source-linked navigation alongside the existing Mojo search index.
No new runtime dependency or external queue service is needed.

Verified locally with 125 native search/intake tests and a real-model Chromium
flow from pasted text through search and glossary source display. See
[the intake guide](knowledge-intake.md) for format, storage and extraction limits.
