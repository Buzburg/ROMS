# ROMS 1.4 verification

Scope: portable task briefs, bounded task-skill authoring and retention, the
ROMS/Buzburg branding update, and release documentation. Base revision:
`9e486d18fc27752b8dc9ee6be0150bdbb76a351b`. Checks ran on October 22, 2026, in
`/home/aeon/Projects/ROMS` using the project's Python 3.12 environment and existing
native artifacts. Publication targets the tested changes plus this evidence record.

## Final local regression result

**1,215 passed, 79 skipped, 49 subtests passed; exit 0**, in 118.71 seconds.
Nine existing fork-related warnings were reported. The final run includes the
source-title improvement and corrected branding assertion. Browser acceptance and
focused brief tests also passed on this implementation. `git diff --check`, changed
Python/JSON parsing and release/setup document link checks passed.

## Portable task brief

The focused suite (`tests/test_knowledge_brief.py`) passed **11 tests** after the
final source-title change. It covers exact excerpts, ordering, constraints, stable
content revisions, source changes and removal, invalid IDs, whole-passage budget
limits, authenticated same-origin HTTP, request-size limits, and read-only MCP use.
No generation model is called by the brief builder.

A headless Chromium acceptance check used the actual loopback knowledge interface,
a temporary database, real document ingestion and local search. It passed:

- Selecting the relevant search passage and generating a brief with constraints.
- Exact equality between the preview, clipboard and downloaded Markdown.
- Clearing the old preview when the task changes.
- Rejecting an empty selection without an export.
- Desktop and 390-pixel mobile layout, with no browser script errors.

Screenshots were manually inspected. That review led to readable source titles in
selection/export and wrapping for long source references. The first browser test
selected a heading-only chunk; it was corrected to select the actual requirements
passage. No product check was weakened to hide that fixture mistake.

The first full-suite run found one old branding assertion expecting “Omarchy OS
Studio.” The packaging test now requires “ROMS” and “Buzburg”; launcher command
compatibility remains checked.

## Local-model task-skill evidence

The [bounded workflow report](bounded-task-skill-agent.md) records real local-model
creation, retention, fresh-session reuse, linked revision, conflict handling, and
manual review limits. That model evidence predates this brief feature; generation
logic has not changed in this release preparation. The brief feature is deterministic
assembly, not another generation workflow.

## Evidence locations and limits

Local raw logs and browser artifacts: `/home/aeon/.codex/benchmarks/roms-1.4/`.
Relevant files: `brief-final.log`, `browser-check-final.log`, `browser-export.md`,
`brief-desktop.png`, `brief-mobile.png`, and `full-suite-final.log`.
Earlier failed attempts are retained as `browser-check.log` history in tool output
and `full-suite.log`; the browser script was corrected and rerun in place.

Full-suite environment uses `OMARCHY_BROKER_BINARY=build/omarchy-broker`,
`OMARCHY_SANDBOX_BINARY=build/staging-sandbox`, `ROMS_PYTHON_PREFIX=.venv`,
`MOJO_PYTHON_LIBRARY` resolved through Python sysconfig, and `PYTHONPATH` with the
checkout and its environment's site-packages. Both `HF_HUB_OFFLINE` and
`TRANSFORMERS_OFFLINE` are set to 1. Command: `.venv/bin/python -m pytest -q`.

Skipped tests do not establish coverage. Generated candidates require human review;
copying evidence into a client does not guarantee a correct answer. Brief exports
are snapshots of selected indexed excerpts, not complete documents or live links.
