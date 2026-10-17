# ROMS

**Your documents. Your machine. One fast search.**

ROMS turns scattered documents, source code and scanned pages into a searchable
local knowledge base for you and your AI tools. Find an exact identifier, recover
a misspelled term, or ask a question in your own words—all through one search.
Results keep their source references so you can inspect the evidence.

[Download ROMS](https://github.com/Buzburg/ROMS/archive/refs/heads/main.zip) ·
[Quick start](#try-one-useful-thing-first) ·
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
- **Build on what you learn.** Retain project lessons, reuse skills and prepare
  bounded, source-backed next steps for review.

In small local tests, ROMS found the intended document first for all 12
messy-document queries, with roughly 6–8 ms median uncached searches after model
loading. These are fixture measurements, not a production speed or accuracy
promise. See the [results and limits](docs/verification/single-search-messy.md).

The lightweight Python demos and preparation tools run on Windows and Linux.
The full Mojo search server targets Linux/WSL. Python remains the adapter for
file formats, model inference and MCP; ROMS is not a pure-Mojo application.
Optional operating-system integrations are separate from the core search setup.

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

From a downloaded or cloned checkout, with **Python 3.11 or later**:

```sh
python -I -S -B scripts/demo_first_run.py
```

No installation, account, model, GPU or network connection is needed. The demo creates a temporary invoice program, introduces a known bad edit and runs a real failing check. ROMS extracts the error from the log, locates the function and restores the original file. The check must pass again before the temporary files are removed and success is reported.

Add `--json` to inspect the original failure log, compacted log, source location and before/after file hashes. The demo accepts no path to your project. It demonstrates controlled recovery, not autonomous repair or safe rollback of concurrent edits. [Verification scope](docs/first-run-demo.md).

## Prepare a task for review

The harness command uses the lightweight dependencies in `requirements-ci.txt`. From the repository root, create a virtual environment and install them:

```sh
python -m venv .venv
```

Use `.venv/bin/python` on Linux or `.venv/Scripts/python.exe` on Windows for the following commands:

```sh
python -m pip install -r requirements-ci.txt
python roms.py harness --request examples/harness-request.json
python -B scripts/demo_harness.py
```

Replace `python` with that environment's executable; shell activation is optional. The [harness guide](docs/HARNESS.md) explains request fields, database setup and examples.

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

Commands for advisory decisions, memory, log compaction and snapshots are listed in `--help`. Utilities can write local state under `data/prefrontal/`; set `ROMS_DATA_DIR` to use another data directory. Snapshot restoration writes files; review its limits before applying it to a real workspace.

Standalone Decision Maker utilities can also persist topic discovery under `ROMS_STATE_DIR` (default `~/.roms`). Harness preparation disables that persistence.

<a id="-10-second-mcp-setup-claude-code-cursor-windsurf"></a>

## Connect an MCP client

The full server needs the runtime packages in `requirements.txt`, a local embedding model, and the required compiled Mojo search module. On Linux/WSL, use `pixi install` and `pixi run build-search`, or install into an environment with Mojo 1.1.0:

```sh
python -m pip install -r requirements.txt
python scripts/build_search_native.py
python roms.py mcp
```

The command uses stdio and waits for MCP messages. For clients with an `mcpServers` configuration, use absolute paths:

```json
{
  "mcpServers": {
    "roms": {
      "command": "/absolute/path/to/ROMS/.venv/bin/python",
      "args": ["/absolute/path/to/ROMS/roms.py", "mcp"]
    }
  }
}
```

For the native search server on Windows, run the Linux environment through WSL. OCR also requires Tesseract with English data and Poppler (`pdftoppm`), included in the Pixi dependencies. See the [search setup guide](docs/search-upgrades.md).

Startup initializes the database, indexes supported files in `knowledge/`, loads local plugins and starts the watcher. The default embedding model is `sentence-transformers/all-MiniLM-L6-v2` on CPU; first use may download model files. Knowledge search and ingestion require the local embedding provider. The index requires 384-dimensional embeddings; changing models requires a compatible rebuilt index. Review [security and data handling](SECURITY.md) before connecting an agent.

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
| Add or refresh documents | `add_knowledge_document`, `reload_knowledge`, `list_knowledge_documents` |
| Retain and recall project lessons | `memory_retain`, `memory_recall`, `memory_get`, `memory_prepare_context` |
| Record or revise lesson evidence | `memory_record_verification`, `memory_correct`, `memory_retract`, `memory_forget` |
| Get an advisory decision | `roms_decide`, `roms_noul`, `roms_score` |
| Find tools and skills | `search_tools`, `list_skills` |
| Read a skill | Resource `skills://{skill_name}` or prompt `get_skill_playbook` |
| Inspect logs and source locations | `roms_sieve_compact`, `roms_symdex_lookup` |

The server advertises the full tool list and schemas on connection. The harness tool uses the server's configured database and skills directory; it does not accept arbitrary paths. Other tools can write knowledge, change lessons, author skills or restore files. Caller-supplied verification records are not authenticated test results.

## Status and limits

ROMS is a developer project for a trusted local operator. Its Python tools, native components and optional integrations have different prerequisites and verification scopes.

- Decision scores and retrieved text can be wrong. They do not establish truth or grant permission to change a system.
- Local plugins run with the server's permissions. Skills and retrieved documents are untrusted input to the agent.
- The optional model gateway needs a separately configured inference service. Installing ROMS does not install model weights or an operating system.
- Dataset export does not train a model. Routing prototypes do not establish measured model-quality improvements.
- Benchmark reports cover specific fixtures and machines. No general latency, token-saving or GPU-performance guarantee is made. The planned 128 GB machine needs its own qualification.

## Verification

The no-install demo has standard-library regression checks:

```sh
python -m unittest discover -s tests -p test_first_run_demo.py -v
```

After installing `requirements-ci.txt` in your environment:

```sh
python -m pytest tests/test_first_run_demo.py tests/test_prefrontal_integration.py tests/test_decisions_jev_laya.py tests/test_release_safety.py tests/test_memory.py tests/test_context.py -q
```

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
