# Bounded local task-skill workflow

Local release candidate, October 22, 2026. Publication is deferred for discussion
with the owner. Repository base: `9e486d18fc27752b8dc9ee6be0150bdbb76a351b`;
changes remain uncommitted. Earlier manual-tool trials are historical evidence,
not the acceptance result for this implementation.

## What changed

ROMS now owns retrieval, evidence assessment, drafting, model review, source
validation and persistence. An outer agent supplies task strings through
`create_task_skill`; it no longer copies nested evidence into generated tool calls.
`draft_task_skill` provides the same drafting path without retention.
`revise_saved_task_skill` accepts an ID or an unambiguous name, preserves the original
request, and links a changed candidate to its parent. Ambiguous names ask for a
choice. Identical revisions reuse the parent rather than creating a self-reference.

Current matching evidence can reuse a candidate without generation. New retrieved
knowledge invalidates that reuse. Source changes withhold stale candidate bodies.
Adverse feedback prevents silent cache reuse; observations remain reports tied to
an exact candidate. Blocker responses identify their source documents.

The retaining Docker Agent profile offers creation, revision, retrieval and feedback.
The separate read-only profile offers unsaved drafting and retrieval. ROMS policy,
not profile instructions alone, denies writes in read-only mode. No procedure
execution tools are exposed by either example.

## Runtime and reproducibility

Working directory: `/home/aeon/Projects/ROMS`. Python: project `.venv` (3.12).
Real-model trials used Gemma 4 E4B Q4_K_M with llama.cpp build 11115, commit
`4d14afc58`, Vulkan AMD 8060S, 8192 context, one slot, reasoning disabled.
Model SHA-256: `85a896a047553e842f25297ee5b031d64ff30147d9c4af17b1e4b394cd1fab87`.
Docker Agent v1.152.0 used the compiled native ROMS MCP server over local stdio.
Generation endpoint: `http://127.0.0.1:18973/v1`, served name `gemma-local`.
All trial data used isolated fixture databases; no user procedure was executed.

Evidence directory: `/home/aeon/.codex/benchmarks/roms-agent-trial`.

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/python scripts/verify_local_skill_agent.py \
  --template agent --scenario all \
  --agent /home/aeon/.codex/benchmarks/roms-agent-trial/docker-agent \
  --model gemma-local --output /absolute/path/to/new-results
```

For direct native MCP authoring cases use `scripts/verify_task_authoring.py
--bounded` with that script's endpoint, model, case and output options.

## Evidence and repairs

- Direct real-model authoring: six of seven main cases passed in
  `bounded-authoring-1`. Empty-library response used the wrong status; after repair,
  `bounded-empty-2` passed without model generation or persistence. Two additional
  cases passed in `bounded-holdout-1` (CSV validation and archive conflict).
  These are nine cases across separate runs, not one clean batch.
- Backup procedure review was strengthened after manual inspection found that a
  completed check was being treated as a passed check. `bounded-backup-2` retains
  pass conditions and failure handling. Original user restrictions remain in the
  candidate even where a generated step does not repeat them.
- First companion attempts chose unsaved drafting despite retaining-profile
  instructions. Separate profiles removed that ambiguity. The next trial saved
  and reused the candidate but asked for its ID instead of revising it. Server-side
  name resolution repaired this dependency on the outer model's planning.
- `bounded-companion-revision-4` demonstrated linked revision and refusal to save
  contradictory requirements. Its source-visibility assertion failed because
  blocker responses omitted document references. References are now returned;
  the assertion was retained for the fresh acceptance run.
- A deterministic regression caught review metadata being replaced with a string.
  The model-review description now uses `generation_review`, preserving the
  required human-review checklist.

## Final repository and workflow checks

`bounded-full-final.log`: **1,204 passed, 79 skipped, 49 subtests passed**, nine
warnings, exit 0 (112.66 seconds). Command: `.venv/bin/python -m pytest -q`.
Runtime overrides used the checkout's `build/omarchy-broker`,
`build/staging-sandbox`, `.venv`, Python shared library from `sysconfig`,
`PYTHONPATH` containing the checkout and `.venv/lib/python3.12/site-packages`,
and `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`. Skipped coverage is not claimed
as verified. YAML parsing passed for all four companion profiles; `git diff --check`
passed.

`bounded-companion-all-5`: exit 0, all 20 workflow checks passed with fresh real
creation (no replay): ordinary-task retention, fresh-session retrieval without a
duplicate, stale-body withholding, a linked revision with the new nonblank reviewer
requirement, preserved original constraints, isolated feedback, conflict detection
and no conflicting candidate saved. Manual inspection confirmed the three original
required fields and four revised nonblank fields. The generated applicability text
is preparation-oriented; it does not authorize later execution.

Manual transcript inspection also found the companion falsely described the blocked
conflict revision as retained despite the correct `persisted=false` tool response.
The automated workflow checks alone do not detect this prose error. The profile now
explicitly instructs it to say no new candidate was saved for blocked results; a
`bounded-companion-conflict-6` retest passed all 13 workflow checks (exit 0),
using a replayed prior candidate. Manual inspection confirmed the final response
said "No new candidate was saved" and explained the conflict. Always use the tool receipt as the
persistence authority. General model reporting reliability remains unproven.

## Limits

This is candidate authoring, not autonomous execution or independently verified
learning. A model can miss contradictions or invent requirements despite structural
validation and a second model pass. Coverage is limited to four complete retrieved
documents and the context budget; more indexed data does not guarantee better skills.
Conflicting sources cause questions only when the assessment/review detects them.
No model-independent semantic proof is claimed. Feedback does not promote a candidate
to verified status. A name search may require more specific keywords or an ID.

The generation server must support JSON-schema responses. Endpoint access is limited
to explicit numeric loopback HTTP addresses, with no redirects or environment proxies.
Each generation request has a 120-second deadline and 128 KiB response limit.
Other local models and Docker container isolation remain unverified for this final
workflow. Earlier Spark and Nanbeige failures are preserved in historical reports.
