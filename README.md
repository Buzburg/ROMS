# ROMS

[![Offline release checks](https://github.com/Buzburg/ROMS/actions/workflows/checks.yml/badge.svg)](https://github.com/Buzburg/ROMS/actions/workflows/checks.yml)

**Your documents. Searchable locally. Ready for your AI agents.**

ROMS turns scattered documents, source code and scanned pages into a searchable
local knowledge base for you and your AI tools. Find an exact identifier, recover
a misspelled term, or ask a question in your own words—all through one search.
Results keep their source references so you can inspect the evidence.

[Download source](https://github.com/Buzburg/ROMS/archive/refs/heads/main.zip) ·
[Quick start](#choose-your-starting-point) ·
[Search setup](docs/search-upgrades.md) ·
[What we tested](docs/verification/single-search-messy.md)

## Why ROMS?

- **Bring the messy files.** Import Markdown, logs, JSON, uneven CSV, PDFs, modern
  Office documents and images. Recover text from scanned pages with local OCR.
- **Search once.** Keyword matching, typo handling and semantic retrieval work
  together. There is no backend menu to configure or extra search server to run.
- **Put Mojo to work.** Compiled kernels handle typo selection, ranking, text
  cleanup and passage splitting. Stored embeddings and a bounded cache keep
  repeat work out of the query path.
- **Keep knowledge close.** Search, embeddings and OCR run locally after setup.
  Connect an MCP-compatible client to make the same knowledge available to your
  agent; that client's own data-sharing settings still apply.
- **Turn knowledge into reusable skills.** Imported guides and checklists become
  source-backed procedural drafts automatically. New evidence updates the drafts;
  revisions, source links and feedback help you decide what to reuse.
  [Explore knowledge-derived skills](docs/knowledge-skills.md).
- **Build on what you learn.** Retain project lessons, reuse skills and prepare
  bounded, source-backed next steps for review.

In earlier MiniLM fixture tests, ROMS found the intended document first for all 12
messy-document queries, with roughly 6–8 ms median uncached searches after model
loading. Those timings do not describe the current EmbeddingGemma Q8 backend
and are not a production speed or accuracy promise. See the [results and limits](docs/verification/single-search-messy.md).

The lightweight Python demos and preparation tools are tested on Windows and Linux
with Python 3.11 and 3.12. The full Mojo search environment targets x86-64
Linux/WSL2. Python remains the adapter for file formats, model inference and MCP; ROMS is not a pure-Mojo application.
Optional operating-system integrations are separate from the core search setup.

## Choose your starting point

| Goal | Start here | Requirements |
| --- | --- | --- |
| Try a controlled recovery demo | [No-install demo](#try-one-useful-thing-first) | Python only; no model or network |
| Import and search your own files | [Local knowledge workspace](#add-knowledge-in-your-browser) | Linux/WSL2, Pixi, compiled Mojo kernels and local embeddings |
| Give an AI client access to knowledge | [MCP connection](#connect-an-mcp-client) | The search environment plus an MCP-compatible client |
| Prepare a task for human review | [Portable harness](#prepare-a-task-for-review) | Python and the lightweight CI dependencies |

Download the source above, or clone the repository:

```sh
git clone https://github.com/Buzburg/ROMS.git
cd ROMS
```

Run the commands below from this directory. The source checkout contains neither
prebuilt Mojo binaries nor embedding weights. The first full setup needs network
access for packages and the embedding model; search and OCR then run locally.

## Five parts

| Part | Purpose |
| --- | --- |
| **Decision Maker** | Rank supplied options, return structured results and abstain when configured thresholds are not met. The current backend uses heuristics; its scores are not calibrated probabilities of correctness. |
| **RAG** | Find relevant document passages through keyword and vector search, with source references and bounded context. |
| **OKF** | Import local knowledge files, preserve document metadata and update their search indexes. |
| **MCP** | Let a compatible agent call registered tools and read resources through one local server. |
| **Skills** | Supply reusable Markdown playbooks. Generated drafts need review before activation. |

The workflow is **request → knowledge and skills → decision → proposed next step → operator approval → separately configured execution**. The preparation API implements the first four steps. It does not execute the proposal or approve itself. See the [component map](docs/components.md).

## Try one useful thing first

From a downloaded or cloned checkout, use **Python 3.11 or 3.12** (the tested versions):

```sh
python -I -S -B scripts/demo_first_run.py
```

No installation, account, model, GPU or network connection is needed. The demo creates a temporary invoice program, introduces a known bad edit and runs a real failing check. ROMS extracts the error from the log, locates the function and restores the original file. The check must pass again before the temporary files are removed and success is reported.

Add `--json` to inspect the original failure log, compacted log, source location and before/after file hashes. The demo accepts no path to your project. It demonstrates controlled recovery, not autonomous repair or safe rollback of concurrent edits. [Verification scope](docs/first-run-demo.md).

## Prepare a task for review

The harness uses the lightweight dependencies in `requirements-ci.txt`. On Linux:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-ci.txt
.venv/bin/python roms.py harness --request examples/harness-request.json
.venv/bin/python -B scripts/demo_harness.py
```

On Windows (PowerShell):

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-ci.txt
.\.venv\Scripts\python.exe roms.py harness --request examples/harness-request.json
.\.venv\Scripts\python.exe -B scripts/demo_harness.py
```

Python 3.11 also works. These commands use the environment explicitly; activation
is optional. The [harness guide](docs/HARNESS.md) explains request fields, database
setup and examples.

The harness demo uses a temporary synthetic knowledge index and selected skill to exercise real retrieval and the public CLI. It prints its checks and removes the fixture afterward.

Preparation retrieves keyword matches from an existing OKF index, reads explicitly selected Markdown skills, and evaluates supplied choices through the current Decision Maker. Retrieval uses the indexed snapshot; it does not revalidate the original documents. The response includes source hashes, a bounded context, a decision or abstention, and a proposed next step. It always reports `approval_required: true` and `execution_allowed: false`.

This path does not call a model, use the network, run tools, edit documents or save topic-discovery records. SQLite may use normal coordination sidecars. It is a preparation step for a caller or operator to review, not a complete autonomous execution loop.

## Other command-line tools

The existing utility CLI uses Python's standard library:

```sh
python roms.py --help
python roms.py index --path .
python roms.py lookup --query invoice_total_cents
python roms.py pack --costs "50,40,30" --values "100,60,50" --budget 70 --required 2
```

Commands for advisory decisions, memory, log compaction and snapshots are listed in `--help`. Utilities can write local state under `data/prefrontal/`; set `ROMS_DATA_DIR` to use another data directory. Snapshot restoration writes files and validates saved paths and content. Older
unbound snapshots require manual recovery; read the [recovery boundaries](SNAPSHOT_SAFETY.md)
before applying a snapshot to a real workspace.

Standalone Decision Maker utilities can also persist topic discovery under `ROMS_STATE_DIR` (default `~/.roms`). Harness preparation disables that persistence.

<a id="-10-second-mcp-setup-claude-code-cursor-windsurf"></a>

## Add knowledge in your browser

On **x86-64 Linux or WSL2**, install [Pixi](https://pixi.sh) and use the repository's
locked environment throughout:

```sh
pixi install --locked
pixi run python scripts/build_search_native.py
pixi run python -c "from app.config import get_embedding_model; get_embedding_model()"
pixi run python roms.py knowledge
```

The model-loading command provisions the default CPU embedding model before the
first import. Keep using `pixi run python` so ROMS sees the packages installed by
Pixi. Open the private local link printed in the terminal. Drop files, select a
folder, or paste text. Imports show progress and retry controls; restarting resumes
interrupted jobs from retained originals. Search, headings and a source-linked
glossary share the same index. [Import guide and limits](docs/knowledge-intake.md).

Alternatively, use a Python 3.11/3.12 virtual environment with
`python -m pip install -r requirements.txt mojo==1.1.0`, build with
`python scripts/build_search_native.py`, and launch with `python roms.py knowledge`.
In that route, every `python` must be the environment's executable, and Tesseract
with English data plus Poppler must be installed separately. Pixi includes them.

## Connect an MCP client

Complete the search setup above, then start the Python MCP server:

```sh
pixi run python roms.py mcp
```

This command uses stdio and waits for MCP messages. For clients with an `mcpServers`
configuration, use the **absolute path to the same environment's Python**:

```json
{
  "mcpServers": {
    "roms": {
      "command": "/absolute/path/to/ROMS/.pixi/envs/default/bin/python",
      "args": ["/absolute/path/to/ROMS/roms.py", "mcp"]
    }
  }
}
```

If you installed with pip instead, use `/absolute/path/to/ROMS/.venv/bin/python`.
Configure the client to launch inside WSL when using the Linux environment from
Windows; a Windows process cannot directly execute this Linux Python binary.

See the [search setup guide](docs/search-upgrades.md) for supported formats and extraction limits.

Startup initializes the database, indexes supported files in `knowledge/`, starts the watcher and loads only explicitly enabled local plugins. ROMS uses only pinned EmbeddingGemma Q8 on CPU; first use may download model files. The 768-dimensional index defaults to `data/embeddinggemma-q8.db`. Re-ingest your knowledge into this new index when upgrading from MiniLM; old databases are preserved. Review [security and data handling](SECURITY.md) before connecting an agent.

Reference repositories used for design inspiration are not required installations.
See the [dependency guide](docs/dependencies.md) for what the runtime actually uses.
Test tools are separate: install `requirements-dev.txt` when running the full test
suite, or use `pixi run -e dev test-search` for native search checks.

### Useful registered interfaces

| Task | Interface |
| --- | --- |
| Prepare a reviewable request | `roms_prepare_harness` with `request_json` |
| Search knowledge | `search_knowledge_base` — one local adaptive engine, shared by chat, grounded context and the Mojo entry point |
| Import status | `get_knowledge_ingestion_status` — unreadable files, recovered-data notes and OCR diagnostics; [search and intake guide](docs/search-upgrades.md) |
| Queue files or pasted text | `queue_knowledge_path`, `queue_knowledge_text` |
| Track imports and retry failures | `knowledge_import_progress`, `retry_knowledge_import` |
| Browse headings and definitions | `knowledge_table_of_contents` |
| Add or refresh documents | `add_knowledge_document`, `reload_knowledge`, `list_knowledge_documents` |
| Retain and recall project lessons | `memory_retain`, `memory_recall`, `memory_get`, `memory_prepare_context` |
| Record or revise lesson evidence | `memory_record_verification`, `memory_correct`, `memory_retract`, `memory_forget` |
| Get an advisory decision | `roms_decide`, `roms_noul`, `roms_score` |
| Find tools and skills | `search_tools`, `list_skills` |
| Read a skill | Resource `skills://{skill_name}` or prompt `get_skill_playbook` |
| Inspect logs and source locations | `roms_sieve_compact`, `roms_symdex_lookup` |

MCP starts in `read_only` mode: search and recall work immediately, while authoring tools require `ROMS_MCP_PROFILE=local`. Rewind and permanent deletion additionally require `ROMS_MCP_ALLOW_DESTRUCTIVE=1`. See [MCP settings](docs/mcp-settings.md) for plugin opt-in and request limits.

The server advertises the full tool list and schemas on connection. The harness tool uses the server's configured database and skills directory; it does not accept arbitrary paths. Other tools can write knowledge, change lessons, author skills or restore files. Caller-supplied verification records are not authenticated test results.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| `ModuleNotFoundError` after installing dependencies | Run with `pixi run python`, or the exact virtual-environment Python used for installation. |
| “Build the required Mojo search module” | Build in that environment with `python scripts/build_search_native.py`, then restart ROMS and its MCP client process. |
| Model loading fails offline | Run `python scripts/fetch_embedding.py` while online using the same user and Hugging Face cache as the service, then enable `HF_HUB_OFFLINE=1`. |
| A scan or image cannot be imported | Check Tesseract English data and `pdftoppm`; inspect the job error or `get_knowledge_ingestion_status`. OCR cannot recover every scan. |
| A changed file still returns old content | A failed update retains the previous index while the watcher retries with backoff capped at 60 seconds. Inspect ingestion status and resolve persistent errors; `reload_knowledge` retries immediately. |
| Deleted files still appear in search | The watcher and `reload_knowledge` remove deleted managed files after a complete scan. If the folder is unavailable or a scan fails, the old index is preserved. Independently imported snapshots remain until explicitly removed. |
| MCP authoring tools are denied | The default profile is `read_only`. Enable `ROMS_MCP_PROFILE=local` only for a client you intend to grant write access. |

See [search setup](docs/search-upgrades.md), [MCP settings](docs/mcp-settings.md)
and [snapshot recovery](SNAPSHOT_SAFETY.md) for detailed boundaries.

## Status and limits

ROMS is a developer project for a trusted local operator. Its Python tools, native components and optional integrations have different prerequisites and verification scopes.

- Decision scores and retrieved text can be wrong. They do not establish truth or grant permission to change a system.
- Local plugins run with the server's permissions. Skills and retrieved documents are untrusted input to the agent.
- The optional model gateway needs a separately configured inference service. Installing ROMS does not install model weights or an operating system.
- Dataset export does not train a model. Routing prototypes do not establish measured model-quality improvements.
- Benchmark reports cover specific fixtures and machines. No general latency, token-saving or GPU-performance guarantee is made. The planned 128 GB machine needs its own qualification.

## Verification

The no-install demo has standard-library regression checks. For the commands in
this section, use your environment's Python (`.venv/bin/python` on Linux or
`.\.venv\Scripts\python.exe` on Windows), or prefix `python` with `pixi run`:

```sh
python -m unittest discover -s tests -p test_first_run_demo.py -v
```

After installing `requirements-ci.txt` in your environment:

```sh
python -m pytest tests/test_first_run_demo.py tests/test_prefrontal_integration.py tests/test_decisions_jev_laya.py tests/test_release_safety.py tests/test_memory.py tests/test_context.py -q
```

For native search, document extraction and the local knowledge interface:

```sh
pixi run -e dev python scripts/build_search_native.py
pixi run -e dev python -m pytest tests/test_search_native.py tests/test_search_upgrades.py tests/test_messy_ingestion.py tests/test_knowledge_intake.py -q
```

The [October 20 review](docs/verification/review-2026-10-20.md) records verified
checks, the index-freshness fixes and recommended follow-up work.
The [harness guide](docs/HARNESS.md) records its checks, and the [CI workflow](.github/workflows/checks.yml) defines the portable test matrix. Native builds and live-model checks have separate prerequisites.

## More documentation

The Linux/Omarchy workshop adds staged changes, registered validation and operator-approved promotion. It requires its own configured runtime and confinement components; those execution features are not established by the portable preparation command or a positive decision score.

- [Release summary](docs/RELEASE_SUMMARY.md)
- [Harness request and response contract](docs/HARNESS.md)
- [Component map and experimental boundaries](docs/components.md)
- [Project lessons and evidence](docs/local-memory.md)
- [Native context selection and scoped measurements](docs/native-context.md)
- [Search setup and supported documents](docs/search-upgrades.md)
- [Current search verification](docs/verification/single-search-messy.md)
- [Retrieval correctness](docs/retrieval-performance.md)
- [Workshop, build evidence and runtime integrations](docs/repository-integrations.md)
- [Omarchy test-build setup](docs/wsl-test-build.md) and [voice setup](docs/voice.md)
- [Chat data handling](docs/chat-privacy.md) and [security boundaries](SECURITY.md)

## License

[Apache-2.0](LICENSE). Copyright 2026 Buzburg LLC. Third-party licenses and acknowledgements remain in [NOTICE](NOTICE) and the relevant source directories.

For local 8-bit EmbeddingGemma embeddings, see [setup and verification](docs/search-upgrades.md#quantized-embeddinggemma).
