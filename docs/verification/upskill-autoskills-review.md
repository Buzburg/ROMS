# UpSkill and autoskills: deeper task-workflow review

This records reference-project findings. Current ROMS implementation and model-test
results are in the [release-readiness report](task-skills-release-readiness.md).

Date: 2026-10-22. This extends the 13-project task-authoring review with implementation
inspection and bounded execution checks of the two projects specifically requested.
The ROMS task-authoring changes remain local; this review does not install either
upstream agent or invoke their teacher/student models.

## Location correction

During this pass, the unpacked autoskills directory was found at
`/home/aeon/ROMS Data/Enhancements/MGP-main/autoskills-main`, rather than the top-level
location used earlier. The top-level `autoskills-main.zip` remains present. The
unpacked CLI-Anything directory also no longer appears at the top level; its ZIP
remains available. No directory was moved by this review.

## UpSkill: more than the benchmark scripts

The earlier review concentrated on `scripts/run_brew.py`, `run_curator.py` and
`build_catalog.py`. Its `cc-integration/` directory adds a substantial user-facing
workflow:

| Mechanism | Code inspected | ROMS application |
| --- | --- | --- |
| Capture user intent and match skills before execution | `capture-prompt.sh`, especially manifest/keyword matching and auto-mode output | Route a task to a relevant existing skill before creating another. Supply applicability reasons and load only selected content. |
| Session-end observations | `hooks/after-session.sh`, `hooks/before-session.sh` | Preserve the task, corrections and outcome observations so the author has evidence for a later revision. Keep process exit, self-report and verified task success distinct. |
| Model-aware authoring | `upskill-build.sh`, generation prompt and model metadata | Write concrete steps at the level the consuming model can follow. Record which model/environment was evaluated; do not imply validation transfers to every local model. |
| Retry and revision loop | `upskill-build.sh`, phase 5 | Reattempt in an isolated task environment and revise based on failures. Adopt the loop design with independent outcome checks. |
| Skill manifest and reuse | `upskill-store.sh`, add/search/sync paths | Save stable identity, task applicability, source revision, model/context and evaluation evidence for reusable skills. |
| Structured artifact extraction | `parse-skill.py`, `test/test_pipeline.sh` | Require an actual valid skill artifact, not a successful subprocess exit or a model's promise to write one. ROMS's task finalizer already rejects missing fields. |
| On-demand delivery | `inject-skill.sh`, `capture-prompt.sh` | The injection helper is a compatibility no-op; real behavior lives in prompt matching and client instructions. ROMS likewise needs a configured client workflow, not just tools exposed by a passive server. |

Two important details temper the README's automation language:

- Session hooks notify the user to run `/upskill-build`; the inspected flow does not
  silently brew every new skill on every prompt. Even auto matching emits an
  instruction to ask whether to apply a match.
- The inspected phase-5 success gate is `grep -q "BUILD_RESULT: PASS"` against the
  student log. It is a text-marker gate, not an independent task verifier. The
  benchmark harness and this client integration must not be treated as equivalent
  evidence of task correctness.

### Executed characterization checks

The complete `parse-skill.py` was read before invoking it on temporary synthetic
inputs. A marked SKILL.md fixture produced a file with exit 0. An input containing
no usable skill also exited 0, but wrote no SKILL.md. Therefore exit status alone
is insufficient for successful authoring; callers must inspect the artifact.

The exact literal pass-marker predicate was separately tested against a synthetic
failure log containing a quoted `BUILD_RESULT: PASS` example. It matched. This
characterizes that predicate only; the full teacher/student loop was not run.
No hooks, installer, global model settings or permission-bypass invocation ran.

## autoskills: context-aware selection and distribution

This project solves a different part of the problem. It discovers the project
stack, maps it to curated existing skills, deduplicates choices, and installs
hash-checked bundles. It is not itself a generator of new task-specific procedures.

Inspected implementation:

- `packages/autoskills/lib.ts`: dependency/config/extension detection, workspace
  resolution, combination rules, installed-skill lookup, and `collectSkills`.
- `skills-map.ts`: technology rules and skill mappings, including combination rules.
- `inventory.ts`: inventory and reading of installed skills.
- `installer.ts`: per-file and bundle hashes plus installed state (prior review).
- `scripts/skill-review.mjs`: fast triage plus stronger adjudication of flagged
  bundles, structured review outputs and input size limits. This is an AI review
  of skill content; it does not certify task quality or replace execution checks.
- `tests/detect.test.ts`, `collect.test.ts`, `workspace.test.ts`, and their helpers.

The strongest ROMS idea is **context-aware skill selection**: use the user's task
plus explicit environment/project facts to decide whether to reuse, adapt, compose
or create. Do not equate a shared keyword with applicability. Preserve a reason for
selection and deduplicate shared capabilities. Bundle identity and lock manifests
become useful if task skills are later saved as multi-file reusable packages.

The local package declares CC-BY-NC-4.0. No source code or registry bundles were
copied into ROMS; this work uses original implementations of design ideas.

### Executed upstream selection tests

Runtime: `/home/aeon/.local/share/mise/installs/node/26.8.1/bin/node`.
Working directory: the unpacked `packages/autoskills` directory above.

```sh
TMPDIR=/tmp/roms-autoskills-audit node --permission \
  --allow-fs-read='/home/aeon/ROMS Data/Enhancements/MGP-main/autoskills-main' \
  --allow-fs-read=/tmp/roms-autoskills-audit \
  --allow-fs-write=/tmp/roms-autoskills-audit \
  --test --test-isolation=none \
  tests/detect.test.ts tests/collect.test.ts tests/workspace.test.ts
```

Result: **249 passed, 13 suites, zero failures/skips**, exit 0. Network, child-process
and native-addon permissions were not enabled. No package installation or registry
download occurred. An initial invocation from the ROMS directory with absolute test
paths did not discover the files under the permission model; running from the
package directory with relative paths corrected discovery without widening write
permissions. This does not verify the installer, remote reviews or whole project.

## Combined ROMS workflow

The full design these projects suggest is:

1. **Understand the task and environment.** Capture the user's actual constraints.
2. **Find an applicable skill.** Match both capability and environment; read its
   source/evaluation freshness before reuse.
3. **Create or adapt on demand.** Retrieve ROMS evidence and let the connected model
   author the task-specific contract. The new prepare/finalize tools implement this
   stage locally, including source checks and an explicit candidate state.
4. **Use and check.** Execute only the user's authorized task. Record actual check
   results separately from the agent's commentary or a helpful-button observation.
5. **Retain selectively.** Persist broadly useful successful procedures with their
   source/model/environment/evaluation metadata; keep narrowly specific artifacts
   task-scoped. Re-evaluate stale or failing skills rather than loading them forever.

Steps 2, 4 and 5 need a reusable authored-skill store, richer applicability matching
and evaluated outcomes to complete the learning loop. The current prototype does
not claim those are implemented. New source information already reaches task-time
preparation; that is distinct from learning from task outcomes.

The remaining projects fit around this workflow: OpenSpace contributes the authoring
and evaluation contracts; SkillOpt contributes repeated-task comparison and revision
feedback; book-to-skill/book2skills contribute source fidelity and procedural form;
AutoMemory and task-observer contribute memory timing and recurring observations;
AnyTool/Docker Agent provide agent execution; CLI-Anything provides tool capability
metadata; RAG-Anything contributes retrieval/import reliability; MGP contributes
memory identity/lifecycle boundaries. Their roles are detailed in
`task-authoring-review.md`; no claim is made that all their functionality is integrated.

Private evidence: `/home/aeon/.codex/benchmarks/roms-agent-trial/` contains
`upskill-characterization.json`, `autoskills-selection-tests.log`, the earlier
ROMS/Docker trial, and the assistant-authored two-source task skill example.
