# Add knowledge once. Find it in one place.

Run `python roms.py knowledge` in the configured native search environment and open
the private localhost URL printed in the terminal. The page accepts files, folder
selection and pasted text, shows import progress, and searches the same Mojo-powered
index used by MCP. No additional service or framework is required.

## What happens to your data

1. ROMS saves an unchanged original under `ROMS_DATA_DIR/imports` (default `data/imports`).
2. A durable SQLite job moves from queued to processing, then ready or failed.
3. The existing bounded parsers, local OCR and Mojo text cleanup prepare passages.
4. Local embeddings, search rows, headings and glossary entries commit together.
5. A failed import keeps its original and diagnostic. Retry after resolving the
   reported problem. Restarting the service resumes work interrupted during processing.

The worker uses an OS lock per database, so two instances cannot process the same
queue simultaneously. Retrying after an index commit is idempotent. Already indexed
content remains searchable while other documents are imported. There is no estimated
percentage: document counts and job states reflect actual work.

The table of contents lists documents and Markdown headings. The glossary extracts
explicit whole-line “TERM means …”, “TERM is defined as …”, and “TERM refers to …”
statements, with source chunk IDs. Clicking an entry displays its indexed source
passage. These are document claims, not independently verified definitions. ROMS
does not invent missing definitions or infer headings in every binary format.
Documents indexed before this feature gain navigation when changed or reimported.

## Limits and local access

Uploads are limited to 32 MiB per file, 1,000 files per selection and 1,000 pending
jobs. Unsupported and excluded files are reported. Existing extraction limits still
apply: see [supported formats](search-upgrades.md). Snapshot storage is retained;
allow disk space for originals and the index. There is no automatic expiration.
Uploading the same file again creates a separate document; retry preserves identity.

The server binds only to 127.0.0.1. A random per-launch token protects API reads and
writes; the URL fragment is moved into browser session storage. Keep that private
link private. Host and Origin checks reject cross-site requests. This is a local
single-user interface, not a multi-user hosted service. Installing model files may
require network access once; import/search processing uses the local model.

## MCP equivalents

- `queue_knowledge_text(name, content)` saves pasted text and returns a job ID.
- `queue_knowledge_path(path, kind="file" | "folder")` snapshots a selected local
  path using the existing source admission rules (32 MiB total per selection,
  Linux/WSL, no links, secret names or dependency directories).
- `knowledge_import_progress(offset=0)` lists job state, attempts and failures.
- `retry_knowledge_import(job_id)` retries a failed original.
- `knowledge_table_of_contents(offset=0)` returns documents and source-linked entries.

Both the UI and MCP use the same durable queue. The existing `knowledge/` watcher
and synchronous import tools remain compatible. An active UI or MCP queue worker
is required to process jobs; closing all ROMS processes pauses pending work.
