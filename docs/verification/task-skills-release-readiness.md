# Task-skill release readiness — 2026-10-22

This records the completed authoring-preview checkpoint. The subsequent saved-candidate
extension is tracked in [the lifecycle report](task-skill-lifecycle.md); its scope and
verification supplement the original evidence below. Publication remains deferred.

## Decision

Ready for a **reviewed skill-drafting preview**, using the tested Gemma 4 E4B
configuration. Changes are local, uncommitted and unpublished. Publishing remains
for a separate discussion with the owner.

This decision covers evidence preparation, client-side assessment/drafting/review,
structural finalization, source freshness, abstention, and portable candidate export.
It does not cover autonomous execution, automatic installation, persistent authored
skill reuse, or learning from verified task outcomes. No generated task was executed.

## Changes

- Added shared Python/native MCP preparation and finalization tools. The connected
  client supplies generation; ROMS does not start or call a generation model.
- Added a separate evidence-assessment contract before drafting. Small-model trials
  showed that combining conflict detection and authoring in one prompt was unreliable.
  The assessment summarizes source requirements before choosing compatibility flags.
- Added explicit needs-information responses. Any acknowledged unknown in a full
  draft also prevents export. Candidates always have `execution_ready: false` and
  a review checklist. Unacknowledged model errors still require review.
- Added optional JSON schemas for constrained generation, exact-value preservation
  instructions, and separate client review guidance.
- Bounded retrieval queries to the search engine's 32-term/128-character limits,
  reporting reductions while retaining complete task text and constraints in the packet.
- Preserved ancestor conditions and heading-only restrictions in extracted drafts;
  kept sibling sections separate and rejected over-budget inherited context.
- Added a repeatable real-model/native-MCP evaluation script and nine synthetic cases.
- Fixed a reproduced test race by publishing a child PID marker atomically. No
  application process-management behavior changed for that fix.

## Verification

Checkout: `/home/aeon/Projects/ROMS`; base commit
`9e486d18fc27752b8dc9ee6be0150bdbb76a351b` plus the local changes.
Project Python 3.12 environment, built native search/MCP/broker/sandbox artifacts,
and cached local embeddings. Model tests used isolated temporary databases and
loopback HTTP. No private knowledge library was modified.

| Check | Result | Evidence under `/home/aeon/.codex/benchmarks/roms-agent-trial/` |
|---|---|---|
| Final `python -m pytest -q` | **1,172 passed, 79 skipped, 49 subtests passed**, 9 warnings; exit 0, 117.24 s | `release-final-suite.log` |
| Focused task/extraction/native-chat/MCP tests | **55 passed, 3 skipped**, exit 0 | `final-focused.log` |
| Real embedding verification | PASS, exit 0 | `release-embedding.log` |
| Real ingestion/extracted skills, feedback, deletion and export | PASS after final extractor change, exit 0 | `release-final-extracted.log` |
| Native MCP protocol checks | PASS, exit 0 | `release-protocol.log` |
| Standalone Docker Agent/native MCP transport | PASS, five tool responses in each of read-only and local profiles; scripted generation | `release-docker-results/` |
| Gemma main authoring cases, seed 42 | **7/7 expected statuses and regression signals**, exit 0 | `gemma-final-authoring/` |
| Gemma fresh cases, seed 17 | **2/2 expected statuses and regression signals**, exit 0 | `gemma-final-holdout/` |

The earlier full-suite failure was an empty PID marker read in
`test_owned_child_disappears_on_cancel_timeout_or_output_overflow[cancel]`;
`release-full-suite.log` preserves it. The final suite includes its atomic-marker fix.
Warnings are existing fork-with-threads deprecation warnings. Skipped optional checks
are not represented as successful verification; see the logs for their scope.

Full-suite environment:

```sh
export OMARCHY_BROKER_BINARY="$PWD/build/omarchy-broker"
export OMARCHY_SANDBOX_BINARY="$PWD/build/staging-sandbox"
export ROMS_PYTHON_PREFIX="$PWD/.venv"
export MOJO_PYTHON_LIBRARY="$(.venv/bin/python -c 'import os,sysconfig; print(os.path.join(sysconfig.get_config_var("LIBDIR"),sysconfig.get_config_var("LDLIBRARY")))')"
export PYTHONPATH="$PWD:$PWD/.venv/lib/python3.12/site-packages"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
.venv/bin/python -m pytest -q
```

Additional commands: `scripts/verify_embeddinggemma.py`,
`scripts/verify_knowledge_skills.py`, and
`tests/test_mojo_protocol.py "$PWD/build/roms-mcp" "$PWD"`, using the same project
Python/runtime environment. The Docker Agent transport script and real-model commands
are documented in their respective workflow pages.

## Real-model assessment

These are development trials and bounded acceptance examples, **not a controlled
model leaderboard or throughput benchmark**. Prompts evolved during development;
other work ran concurrently. Final manifests record code/fixture hashes, runtime,
seed and endpoint. Both final Gemma suites report no source changes during execution.

- **Spark Q4:** exposed reasoning-budget exhaustion, invalid JSON, source conflicts
  hidden in otherwise valid drafts, and unnecessary questions. A separate evidence
  assessment improved conflict detection, but drafting still withheld complete tasks.
- **Local Sakura–Nanbeige 4.2 3B:** its embedded template failed structured sampling
  with the installed runtime. Native ChatML formatting (`--chat-template chatml
  --no-jinja --reasoning off`) enabled generation. Evidence-first assessment corrected
  a false conflict, but the drafting stage still asked unnecessary questions. It is
  not qualified here as a default author for this workflow. Interrupted template
  trials are environment failures, not completed quality tests.
- **Gemma 4 E4B Q4:** initially omitted the exact SQLite success value while preserving
  the broader procedure. After exact-value preservation was added to drafting/review,
  it passed the seven original cases and two fresh cases without further prompt changes.

Final model: [Unsloth Gemma 4 E4B GGUF](https://huggingface.co/unsloth/gemma-4-E4B-it-GGUF),
revision `bfc15c382204943c3a8fff0c750b94ae2364d7a3`,
`gemma-4-E4B-it-Q4_K_M.gguf`, 4,977,171,584 bytes.
SHA256 verified against the published file metadata:
`85a896a047553e842f25297ee5b031d64ff30147d9c4af17b1e4b394cd1fab87`.
Local copy: `/home/aeon/Models/roms-authoring-gemma4/`.

Runtime: installed llama-server build 11115, commit `4d14afc58`, Vulkan on AMD Radeon
8060S. Server flags: `--host 127.0.0.1 --port 18973 -c 8192 -ngl 99 --reasoning off`.
Assessment temperature 0.3; drafting/review temperature 0; JSON-schema output;
`enable_thinking=false`. Seeds 42 and 17 for the main and fresh suites respectively.

## Manual output review and limits

The final four candidate exports were inspected against their packets:

- Backup: retains approval, stop-before-copy, a new destination with no overwrite,
  read-only validation, exact `ok`, and leaving the writer stopped on failure.
- Report archive: retains copying to a new destination and byte-count mismatch
  escalation; ignores the embedded hostile override and does not claim execution.
- Invoice review: preserves compared fields, arithmetic/subtotal checks, holding
  discrepancies for the owner, and no sending/payment authorization.
- CSV validation: preserves required columns, the less-than-10 and greater-than-0
  thresholds, stopping/escalation, and no input modification or publication.

The archive draft body does not repeat the explicit no-deletion sentence; the full
export preserves it in the original user constraints, and its only action is copying.
Clients must consider the original task and constraints as well as the generated body.
An empty unknowns list is not proof of completeness. Keyword signals alone cannot
establish entailment, correct ordering or safe execution.

Five other cases appropriately withheld a skill: missing inputs, conflicting backup
policies, unrelated evidence, an empty library, and conflicting retention policies.
The empty-library case makes no generation call.

The harness controls MCP tool order; it does not certify a model's autonomous tool
selection in arbitrary clients. The Docker Agent live transport check uses scripted
model output. Model review is not an independent verifier. No procedure was executed,
no outcome-learning loop was tested, and no artifact was automatically installed.

Refresh existing extracted drafts after upgrading to pick up ancestor context.
Large-document omission and bounded retrieval remain documented limitations. The
release notes deliberately describe reviewed drafting rather than autonomous learning.
