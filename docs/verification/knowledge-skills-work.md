# Knowledge-derived skill upgrade

Base: 7c836f9. Scope: triage 132 local ZIP archives and the Skills/Any folders;
implement automatic source-backed procedural drafts, incremental updates,
deduplication, revision-aware feedback, discovery and portable Markdown export;
verify ingestion, deletion, UI/API/CLI/MCP contracts; publish a source release.

Acceptance: importing procedural documents produces usable cited drafts without
an LLM service; adding relevant evidence expands a draft without duplicate steps;
changed/deleted sources cannot leave current-looking stale instructions; feedback
is tied to the exact revision; source text never runs code or silently activates
skills. Existing manual skills remain untouched. Nonprocedural content is skipped.

Reference review is static: no archive installers, agents or scripts are executed.
Implementation is original ROMS code using design ideas, not copied vendor code.
Root README/license triage is not a full security audit of every archive member.
Private source content, caches and archives will not be published.

Implementation and local verification are complete; source publication follows these checks.

## Completed evidence (2026-10-22)

Working directory: `/home/aeon/Projects/ROMS`. Base revision:
`7c836f9471f4ee9ce4524f30ea31c3e0b64270e5`; tested changes are the knowledge-skill
feature committed with this record. Python: project `.venv/bin/python` (3.12).
Native search, broker, sandbox and MCP binaries were available locally. Model
inference used the existing local cache with `HF_HUB_OFFLINE=1` and
`TRANSFORMERS_OFFLINE=1`. `PYTHONPATH` included the checkout and venv site-packages;
`ROMS_PYTHON_PREFIX`, `MOJO_PYTHON_LIBRARY`, `OMARCHY_BROKER_BINARY` and
`OMARCHY_SANDBOX_BINARY` pointed to the project runtime and build artifacts.

| Check | Command / procedure | Result |
| --- | --- | --- |
| Full suite | `.venv/bin/python -m pytest -q` | PASS: 1,146 passed, 79 skipped, 9 warnings, 49 subtests; 64.28 seconds |
| Final focused suite after adding pagination regression | `.venv/bin/python -m pytest tests/test_knowledge_skills.py -q` | PASS: 13 passed |
| Real inference and native parsing | `.venv/bin/python scripts/verify_knowledge_skills.py` | PASS: ingestion, automatic citations, retrieval, additional variants, revision-specific feedback, export, repeatable backfill and source deletion |
| Compiled MCP server | `.venv/bin/python tests/test_mojo_protocol.py build/roms-mcp "$PWD"` | PASS: new tools registered, existing protocol checks, rejected invalid input, clean startup-error stdout |
| Browser | Chromium with synthetic staging-guide database, loopback server and Playwright | PASS: review, source passage, feedback observation, Markdown download, 390px viewport without horizontal overflow, no JavaScript errors |
| Diff | `git diff --check` | PASS |

The first full run exposed a startup test fixture that stubbed database setup but
not the new backfill. The fixture now records and asserts that backfill runs once.
The CLI subprocess test now explicitly uses the parent's tested Python import
paths, matching the native-test environment. Both are superseded by the passing
full/focused runs above. No production behavior was disabled to pass these tests.

Raw local logs were captured under `/tmp/roms-skills-*.log`; the archive inventory,
Chromium screenshot and synthetic exported draft are retained privately under
`/home/aeon/.codex/benchmarks/roms-enhancements/`. No private source documents,
archives or model files are committed. Browser dependencies were installed only
into a temporary testing directory, not project runtime requirements.

The full suite's skipped tests are not claimed as executed integrations. Browser
coverage is Chromium only. Reference triage is not an exhaustive archive-code
audit. Draft generation is extractive and English-verb-based; correctness of an
arbitrary imported procedure remains unverified. This evidence records local
checks; consult the exact published commit's GitHub Actions run for hosted CI.
