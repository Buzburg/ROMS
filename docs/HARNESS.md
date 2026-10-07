# Portable ROMS harness

ROMS prepares work by combining the existing Decision Maker with retrieval, indexed Open Knowledge Format (OKF) records and selected Markdown skills. The same preparation API is available through the CLI and MCP. It runs on Windows and Linux; Omarchy is optional. macOS has not been verified.

## Run it

Use Python 3.11 or later in an environment with `requirements-ci.txt` installed. From the repository root:

```sh
python roms.py harness --request examples/harness-request.json
python -B scripts/demo_harness.py
python -B scripts/demo_harness.py --json
```

The example describes a failed invoice check and offers two possible responses. With no knowledge index, preparation evaluates the supplied observations and reports that retrieval is unavailable. It does not create an empty database or claim a search succeeded.

The demo creates a **synthetic temporary OKF/FTS index**, a selected skill and a request. It exercises the real public CLI, retrieval and Decision Maker, checks the proposal and hashes, verifies that the index and decision-state directory are unchanged, and removes the fixture. This tests preparation, not ingestion, model quality or real invoice processing. It needs no model, GPU, account or network service.

For your existing ROMS index and skills, use operator-selected paths:

```sh
python roms.py harness --request examples/harness-request.json --db /path/to/roms.db --skills-dir /path/to/skills
```

On Windows, paths such as `"D:/My Project/roms.db"` work. Defaults are `ROMS_DB_PATH` (otherwise `data/roms.db`) and `ROMS_SKILLS_DIR` (otherwise `skills/`), resolved by the existing configuration module.

Create or update the index separately with existing OKF ingestion. Full MCP startup indexes supported files in the configured knowledge directory; `add_knowledge_document` and `reload_knowledge` update it. Those operations require `requirements.txt` and the configured embedding backend, write data, and may download models or call a remote embedding endpoint. Preparation only uses the existing keyword index; it does not request embeddings or open original knowledge files.

## Request contract

CLI/MCP requests are strict JSON objects, at most 32 KiB of UTF-8. Duplicate keys, nonfinite numbers, unknown fields and malformed data are rejected.

| Field | Required | Limit and meaning |
| --- | --- | --- |
| `goal` | Yes | Nonempty text, at most 2,048 characters. The question is separate from evidence. |
| `options` | Yes | 2–10 named descriptions, each at most 512 characters. IDs use 1–64 letters, digits, underscores or hyphens and begin with a letter or digit. The caller supplies possible next steps. |
| `evidence` | No | Up to 4,000 characters of observed information. Default empty; supplied claims are not authenticated. |
| `skills` | No | Up to four Markdown leaf names, such as `invoice-review` or `invoice-review.md`. No directory traversal, linked files or duplicate resolved names. Each file is limited to 32 KiB. Default empty. |
| `max_context_chars` | No | Integer from 512 to 16,000; default 6,000. Shared budget for evidence, retrieved excerpts and skill text, in that order. |

The budget counts characters, not model tokens or JSON bytes. Goal, choices and metadata have separate limits. Truncated or entirely omitted sources are listed; empty excerpts do not become evidence. Skills are untrusted playbook text and do not affect decision scores. Selected skills can be omitted by the budget.

The inline CLI supports `--goal`, JSON `--options`, `--evidence`, repeated `--skill`, and `--max-context-chars`. These cannot be mixed with `--request`. See `python roms.py harness --help`. A valid report, including abstention, exits 0. Invalid requests or unreadable configured sources exit 2 with no success report.

## Response contract

The report identifies itself as `schema: "roms.harness/v1"`.

| Field | Meaning |
| --- | --- |
| `status` | `review-required` when the heuristic offers a suggestion, otherwise `abstained`. |
| `decision` | Actual Decision Maker output, reasons for abstention, option scores and an explicit advisory marker. |
| `proposed_next_step` | Supplied description of the suggested option, or `null` on abstention. An internal highest-scoring choice can remain inside an abstained decision; do not execute it. |
| `context.evidence` | Budgeted observation text, original supplied-text SHA-256 and truncation flag. |
| `context.knowledge` | Retrieval status and up to three matches from existing ROMS `lexical_search` / SQLite FTS5. Each source has an OKF document ID, title, registered `index_checksum`, full `indexed_chunk_sha256`, returned `snippet_sha256`, excerpt and truncation flag. |
| `context.skills` | Selected text, `skills://` reference, full-file SHA-256, untrusted-input label and truncation flag. |
| `context.coverage` | Actual supplied character count, budget and truncated/omitted source references. |
| `backend` | Declares `lexical_heuristic`, `model_called: false`, uncalibrated scores and no persisted topic discovery. |
| `approval_required` | Always `true`. |
| `execution_allowed` | Always `false`. |

Original source files are **not revalidated**: `source_file_validated` is always false. Stored checksums identify the index snapshot, not current files or authenticated truth. `snippet_sha256` covers exactly the returned UTF-8 excerpt, including an empty string when omitted. Evidence and skill hashes cover full inputs before truncation. Hashes detect byte changes only when compared with a trusted reference; they are not signatures or execution receipts.

Knowledge reads use a consistent read-only SQLite transaction. They do not update logical records; SQLite may use coordination sidecars for a live WAL index. Missing indexes are reported as unavailable. Existing but invalid, busy, oversized or unreadable indexes fail visibly. Refresh stale knowledge separately and rerun preparation.

## MCP and Python

`roms_prepare_harness` takes one `request_json` string containing the same object. The server supplies database and skills roots; callers cannot override them in the request. Connect through `python roms.py mcp` as described in the [README](../README.md#connect-an-mcp-client). Full server startup and other tools have their own side effects and permissions.

Python integrations call `app.harness.prepare_request(request, db_path=..., skills_dir=...)`. Text transports should first call `app.harness.decode_request(raw_json)` to enforce byte and JSON rules. Filesystem roots are trusted operator configuration, never model-supplied request fields.

## What happens after preparation

An operator or caller reviews the goal, evidence, freshness, skill text and proposed next step. Preparation provides no automatic executor, patch approval, model loop or auto-commit. Missing, unrelated, negated or uncertain evidence can cause abstention; other word-overlap mistakes remain possible. A high score cannot establish entailment, factual correctness or permission.

For staged code changes, the separately configured **Linux workshop** provides its own draft, validation and approval path. It binds promotion to reviewed changes and existing validation rules. It remains optional; portable preparation does not import Linux-only execution code or weaken its checks. Generic utilities and snapshot restoration have narrower guarantees; see the [component map](components.md).

## Verification

```sh
python -m pytest tests/test_harness.py tests/test_harness_cli.py tests/test_decision_boundaries.py tests/test_decisions_jev_laya.py tests/test_retrieval_quality.py -q
python -B scripts/demo_harness.py
```

These cover actual FTS retrieval, provenance, no logical database mutation, truncation hashes, skill isolation, strict inputs, abstention boundaries, the public CLI and MCP client/server transport in memory. Symlink checks can skip on Windows hosts without symlink privileges. The [CI matrix](../.github/workflows/checks.yml) runs on Windows and Ubuntu with Python 3.11 and 3.12. These checks do not qualify macOS, native Mojo kernels, live models, the future 128 GB machine or autonomous execution.
