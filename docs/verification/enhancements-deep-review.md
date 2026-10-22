# Docker Agent trial and enhancement implementation review

Historical source review and transport checkpoint. See the later
[release-readiness report](task-skills-release-readiness.md) for the current implementation and model trials.

Date: 2026-10-22. ROMS base: `9e486d18fc27752b8dc9ee6be0150bdbb76a351b`.
Scope: Docker Agent interoperability and implementation-focused review of all 13
projects in the supplied `ROMS Data/Enhancements` collection. Twelve projects have
unpacked folders; `book-to-skill-master` was inspected inside its ZIP without
extracting or running it. This is deeper than the earlier README inventory, but
is not an exhaustive audit of every file, vendored application or dependency.

## Trial result

**PASS: Docker Agent can use ROMS as a separate local MCP service.**

The official standalone Linux binary v1.152.0 was downloaded into a private trial
directory. SHA-256 matched GitHub's release-asset digest:
`bb591b3b73e6ce06b24a19732371fefb5a99f001813c94e146a4b1474135c8e8`.
The local reference folder was inspected as source; its installers were not run.

The repeatable `scripts/verify_docker_agent.py` test uses a synthetic staging guide,
real ROMS ingestion/native parsing/local embedding inference, the compiled
`build/roms-mcp` subprocess, and the real Docker Agent client. A loopback HTTP server
supplies scripted streaming model responses. The scripted calls use known fixture
arguments; they do not demonstrate an AI choosing the right skill.

| Check | Observed result |
| --- | --- |
| Skill search through Docker Agent and MCP | PASS: seeded skill returned |
| Read skill detail | PASS: source revision returned |
| Attempt feedback in ROMS read-only profile | PASS: ROMS denied write; database unchanged |
| Submit feedback in local profile | PASS: one observation persisted for the exact revision |
| Execute backup or improve a skill | NOT TESTED; no task executor or generation model was used |
| Docker container sandbox | BLOCKED: permission denied on this account's Docker socket |
| Real local generation model | NOT TESTED: no generation server was listening during preflight |

No production knowledge database was used. Telemetry and automatic tool installation
were disabled. Only search, detail and feedback were exposed to the trial agent;
the synthetic feedback explicitly says no backup was executed. The test completed
and its temporary HTTP server shut down. This establishes client interoperability,
not autonomous task success, performance, isolation of arbitrary tools, or learning.

An optional configuration and usage notes are in `examples/docker-agent/`.
No ROMS runtime dependency was added and no production server behavior changed.

## Implementation findings by project

Source paths below are relative to each named local project. Tests mentioned here
were **read**, not executed, unless explicitly identified as ROMS trial checks.
Archive documents were treated as reference material, not instructions to follow.

| Project | Implementation and test evidence inspected | Benefit for ROMS and decision |
| --- | --- | --- |
| Docker Agent | `docs/tools/mcp/index.md` local stdio command/env/tool filtering; `docs/configuration/telemetry/index.md`; CLI v1.152.0 runtime and actual MCP trial | Keep as an optional client. It already supplies an agent loop; ROMS can provide knowledge. Telemetry defaults on in the reference documentation, so the trial explicitly disabled it. Standalone MCP does not imply container isolation. |
| OpenSpace | `openspace/skill_engine/evolution/admission.py`, `behavior_eval.py` (especially `SkillBehaviorEvaluator` and replay handling); `tests/skill_engine/evolution/test_admission_capture.py`; `tests/skill_engine/test_evolution_retry_idempotency.py` | Highest-value design: evidence admission, candidate staging, repeatable evaluation, stable retry identity. Strict replay is the default, but the implementation permits optional replay; ROMS should distinguish those states and never label a non-replayed revision verified. Do not import the whole runtime. |
| SkillOpt | `skillopt/optimizer/slow_update.py`; `tests/test_optimizer_feedback_flow.py` | Compare the same tasks under old/new revisions. Its feedback regression explicitly checks that private verifier syntax stays out of optimizer prompts/proposals. Adopt that separation to reduce teaching a skill to satisfy the test string instead of the task. The slow-update code passes full comparison context; ROMS would need explicit context/resource budgets. |
| UpSkill | `scripts/run_curator.py`, `scripts/build_catalog.py` | Consolidates category-specific guidance and feedback; selects guidance by category/keyword overlap. The catalog truncates selected content at 500 characters, and the curator invokes an external agent. Useful patterns, but do not inherit truncation that can lose a procedure's checks or assume the external agent is available locally. |
| autoskills | `packages/autoskills/installer.ts` (`verifyRegistryEntry`, bundle checks); `tests/installer.test.ts` (tampering, local/cache installs, lockfile preservation) | Add export manifests and integrity checks if ROMS grows multi-file skill bundles. Hashes prove content identity, not instruction quality. Agent-folder symlink installation should remain an explicit operation. Current single-file exports do not need an entire registry installer. |
| book-to-skill | ZIP: `tools/validate_skill.py`, `tests/test_validate_skill.py`; evaluation/source-test filenames inventoried | Host-specific frontmatter validation distinguishes errors from ignored fields; tests include UTF-8 BOM handling. Useful export compatibility checks. The archive has evaluation/replay tooling, but only validation implementation was inspected deeply; no behavioral-quality claim is made about it. |
| book2skills | `skills/skill-creator/scripts/quick_validate.py`; `skills/war-of-art-pressfield/SKILL.md` structure/source references | Useful separation of applicability, procedure and source material. Validator checks required fields, supported properties and naming. This is a skill collection/authoring pattern, not evidence that arbitrary books automatically yield correct skills. Individual content licenses vary; do not bulk redistribute book-derived material. |
| one-skill-to-rule-them-all | `scripts/validate-skill-bundle.py` validation/round-trip contract and bounds; observation-log reference from prior review | Validate exports against the actual consumer and verify package round trips. Its core-size ratchet is project-specific; borrow bounded-loading discipline, not that project's exact limits or embedded instructions. |
| AutoMemory | `reference/hub/ask_ref/cli.py`; `commands/auto-memory-refine.md` | Primarily a catalog and agent-driven memory-design/refinement workflow. Persistent phase state and explicit stopping limits are useful. Its critic/improver instructions are not an installed ROMS service and were not executed. Thousands of files under bundled use cases were not exhaustively audited. |
| AnyTool | `anytool/agents/grounding_agent.py` bounded loop, backend scope and `_check_task_completion`; `grounding/backends/mcp/installer.py` | Scope tool exposure and preserve execution records. Default scope includes GUI/shell/MCP/web/system; its completion helper recognizes an assistant marker. ROMS should demand an independent task check before recording verified success. Broad desktop automation is unnecessary for the initial companion. |
| CLI-Anything | `cli-anything-plugin/skill_generator.py` (`extract_cli_metadata`, AST-based `extract_commands_from_cli`); `tests/test_skill_generator.py` | Generate accurate capability documentation from known command definitions without importing/executing target application code. Tests inspect grouped command names and generated sections. Useful for future ROMS CLI skills; examples still need executable verification. The many app-specific harnesses were not individually audited. |
| RAG-Anything | `raganything/batch.py`; `tests/test_batch_rag_incremental.py` including failed insertion retry and different-workspace cases | Strong import reliability idea: parsing completion and indexing completion are different states. Reuse successful parsing while retrying failed indexing; do not mistake a parser cache hit for a fully indexed document. Its LightRAG/multimodal stack is a larger dependency commitment, not a drop-in ROMS upgrade. |
| MGP | `reference/gateway/routes/memory.py` request/response validation, tenant binding and audited writes; `sdk/python/tests/test_retry.py` | Explicit identity, lifecycle and retry contracts are valuable when sharing memory across agents. The retry test simulates a 502 followed by success; that alone does not prove exactly-once writes. ROMS already has idempotent feedback IDs; extend that discipline before adopting another protocol/gateway. |

## Confirmed ROMS gap

A direct synthetic test of `replace_sources` used:

```markdown
# Credential rotation
Requires operator approval and a tested rollback plan.
## Steps
1. Create a replacement credential.
2. Remove the previous credential.
```

A draft is generated, but the prerequisite sentence is absent: the section split
keeps child-section text and drops its parent context. This is a confirmed
limitation in v1.3.0, not a claim about the upstream projects. Candidates still
carry source references and review warnings, but those do not replace missing
prerequisites. The original source must be checked before use.

This review did not change the extraction algorithm. A follow-up fix should retain
relevant ancestor context with citations, or clearly mark context as incomplete;
never silently clip the added context. Its tests should include nested headings,
sibling prerequisite sections, context spanning chunks, and bounded oversized input.

## Recommended order

1. **Preserve prerequisites and validate exports.** Fix the reproduced context gap;
   add structural checks and host-compatibility cases. Acceptance: no silently lost
   prerequisites in nested-section fixtures, stable citations and bounded output.
2. **Measure skill retrieval.** Add positive tasks and negative near-misses; then
   evaluate semantic ranking against the current keyword baseline. Acceptance:
   measured retrieval improvement without increasing irrelevant skill selection.
3. **Separate observations from verified outcomes.** Record task/environment,
   revision, artifact references and an independently checked result. A model's
   “success” message and the current helpful button remain observations.
4. **Stage revisions and replay tasks.** Let a local model propose a revision;
   compare baseline and candidate on the same held-out tasks, with a failure budget
   and rollback. Keep source quotations and model-generated instructions distinct.
5. **Extend the optional agent.** Only after the above checks, grant specific task
   tools and measure completed tasks, latency and resource use. Start with one agent;
   multiple agents should earn their extra inference cost in comparisons.
6. **Improve import resumability and bundle integrity where needed.** These can
   improve reliability independently of an agent or a large orchestration stack.

## Evidence and limitations

Local runtime: `/home/aeon/Projects/ROMS/.venv/bin/python`, Python 3.12; existing
compiled native MCP and cached embedding model. Trial command:

```sh
HF_HUB_OFFLINE=1 .venv/bin/python scripts/verify_docker_agent.py \
  --agent /home/aeon/.codex/benchmarks/roms-agent-trial/docker-agent \
  --output /home/aeon/.codex/benchmarks/roms-agent-trial/results
```

Result: exit 0, two profiles, three MCP responses per profile; assertions checked
actual tool responses and final database state. The final run follows the portable
Python site-packages path correction. Private trial evidence is under
`/home/aeon/.codex/benchmarks/roms-agent-trial/`: `results/result.json`, transcripts,
synthetic model requests, `extraction-gap.json`, and an inspected-source hash manifest.
The downloaded executable is an optional local testing artifact, not bundled in ROMS.

The existing release's hosted workflow 39793266591 is now successful for commit
`9e486d1`; that result predates this trial script and does not certify these new files.
No real-model quality benchmark, container sandbox, upstream test suite, or complete
third-party security/license audit was performed. No upstream implementation was
copied. These trial and review deliverables are local and have not been published.
