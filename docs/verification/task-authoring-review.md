# Task-time authoring review and implementation

Historical implementation checkpoint. The [release-readiness report](task-skills-release-readiness.md)
supersedes the model-testing and extractor limitations recorded below where noted.

Date: 2026-10-22. Base ROMS revision: `9e486d18fc27752b8dc9ee6be0150bdbb76a351b`.
Scope: revisit all 13 enhancement projects specifically for creating a skill from
ROMS information when a user's task needs one, rather than extracting pre-existing
procedures or only learning after a task ends. Preserve earlier local trial files.

Acceptance: return current task-relevant evidence; allow the connected agent to
synthesize a new procedure across sources; validate citations and source freshness;
return a usable task-specific candidate; abstain when source evidence is absent;
retain prerequisites in included documents; verify both MCP servers' shared tools.

## Findings against the clarified goal

All paths below are relative to the named project under the supplied Enhancements
collection. They are reference data, not instructions adopted by the implementation.
This was targeted source/prompt inspection, not an exhaustive dependency audit.

| Project | Revisited evidence | Fit for creating skills when needed |
| --- | --- | --- |
| OpenSpace | `openspace/skill_engine/evolution/authoring.py` `_build_prompt`, `authoring_contract.py`, `capture_contract.py` | Closest authoring architecture: evidence packets, intent, trigger/non-trigger conditions, and derived/captured procedures. Borrowed the structured authoring contract and explicit source references, not its runtime. |
| UpSkill | `scripts/run_brew.py` `build_brew_prompt`; `scripts/build_catalog.py` | A teacher generates a checklist from task + trajectory + outcome. This is mostly after-task distillation. ROMS needs the same task conditioning before execution, using retrieved evidence instead of assuming a prior trajectory exists. |
| SkillOpt | `skillopt_sleep/mine.py`, `prompts.py` `_REFLECT`, `staging.py` | Mines recurring tasks and proposes bounded reusable edits from failures. Useful for the later improvement loop, but its generic-preference optimization is not the initial per-task skill generator. |
| book-to-skill | ZIP `SKILL.md` conversion/analysis/update modes and named-framework preservation; validator reviewed previously | Source-grounded synthesis belongs in the authoring model. Its full conversion pipeline is batch-oriented; task authoring should retrieve only the relevant evidence and preserve exact source terminology. No upstream workflow was executed. |
| book2skills | `README.md` collection structure; representative skill applicability and source references | Useful examples of actionable frameworks grounded in source material. This is a collection, not an autonomous task router/generator. |
| one-skill-to-rule-them-all | `SKILL.md` observation/review triggers; `references/skill-authoring.md` | Captures recurring observations and authors during review. Useful for deciding which temporary skills deserve later reuse; it is not a live synthesis engine to embed unchanged. |
| AnyTool | `anytool/agents/grounding_agent.py` model/backend setup and execution loop | Supplies task reasoning/tool selection. It does not make ROMS knowledge a skill automatically; the agent needs a task-authoring tool contract and workflow instruction. |
| AutoMemory | `commands/auto-memory-design.md` write timing, recall timing, injection point and budget fit | Valuable design distinction: information must be retrieved before the task decision and injected where the agent can use it. This is agent-guided design material, not a runtime dependency. |
| CLI-Anything | `cli-anything-plugin/skill_generator.py` metadata/AST/command-example generation | Good for stable tool capability descriptions. Those are ingredients a task author might use, not a general synthesizer over a knowledge library. |
| RAG-Anything | `raganything/query.py` `aquery` and generation/retrieval options | Retrieves and answers from evidence. The missing ROMS piece is structured procedural authoring after retrieval; a new retrieval framework is unnecessary for this first path. |
| autoskills | `packages/autoskills/inventory.ts` skill discovery/read paths; installer previously reviewed | Inventory/distribution/reuse infrastructure. It does not supply task-conditioned generation. Keep installation separate from ephemeral skill use. |
| MGP | `reference/gateway/routes/memory.py` policy/validation/identity | Useful memory interchange and lifecycle boundaries. A memory protocol cannot itself synthesize a procedure; not needed in the initial authoring path. |
| Docker Agent | `pkg/runtime/sampling.go`, `pkg/tools/mcp/session_client.go`, local MCP configuration | Can act as the author and consumer. Source inspection found sampling support, but SDK/spec verification found that feature deprecated. Ordinary prepare/finalize tool calls keep authoring in the client's normal model loop. |

## Compatibility correction

The initially investigated server-initiated sampling route is implemented by Docker
Agent, but the installed MCP SDK flags it deprecated. The official
[2026-07-28 release notes](https://blog.modelcontextprotocol.io/posts/2026-07-28/)
and [sampling specification](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/draft/client/sampling.mdx)
confirm new implementations should not adopt it. No sampling dependency was added.

## Implementation and boundaries

`app/task_skills.py` implements preparation and finalization. Both Python and native
MCP servers receive the new tools through `register_knowledge_skill_tools`.
The optional Docker Agent configuration instructs its model to author a contract
between the two calls. The server returns evidence and validates model-authored
content; it does not masquerade extraction as model generation.

This task-time path preserves complete indexed context for included sources. The
older import-time section extractor remains unchanged and retains the limitation
recorded in the preceding review. Source omission and input/output budgets are
explicit. Large documents may be omitted rather than clipped. Source freshness is
checked at finalization; any returned artifact remains a snapshot afterward.

This is task-scoped authoring, not persistent self-improvement. No generated skill
is installed or automatically executed; no success is inferred from valid citations.
No upstream implementation code was copied. Client model quality and tool invocation
reliability still require a real-model benchmark.

## Evidence

Local environment: project Python 3.12 venv; built native MCP/search/broker/sandbox;
existing local embedding cache; offline model flags and project Python import paths.

- Focused suite: `pytest tests/test_task_skills.py tests/test_knowledge_skills.py tests/test_mcp_security.py -q`: 38 passed before the annotation-only network hint change.
- Docker Agent v1.152.0: `scripts/verify_docker_agent.py` against the real native MCP
  process, both read-only and local profiles: PASS, five actual MCP responses per
  profile. Preparation/finalization used the real tool-returned evidence packet.
  Model authoring was scripted; no task was executed. Logs are retained privately
  under `/home/aeon/.codex/benchmarks/roms-agent-trial/task-results/`.
- Source-review pointers are retained in `task-authoring-review.json` in that private
  directory's parent. No private knowledge library was imported or modified.

Final full suite: `pytest -q` with the project native runtime environment: **1,160
passed, 79 skipped, 9 warnings, 49 subtests passed**, 65.39 seconds, exit 0. Log:
`/tmp/roms-task-full.log` (also copied to the private trial evidence directory).
This supersedes the focused run and includes the annotation change. Final edits
after that run were documentation, a test's unused import, and a script comment.

An additional worked example used real ROMS retrieval over two synthetic documents.
This assistant inspected the returned packet and authored a combined staging SQLite
backup skill with approval, non-overwrite, integrity-check and failure-handling
requirements. Finalization passed. Artifacts: `task-demo/prepared.json`,
`task-demo/authored.json`, `task-demo/result.json`, and `task-demo/SKILL.md` in the
private trial directory. This was assistant-authored, not autonomous local-model
inference, and no backup operation was executed.

Final diff/whitespace review passed. The implementation and trial files remain
local, uncommitted and unpublished. No claim of production deployment is made.
