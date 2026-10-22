# Automatic task skills: current readiness

Historical manual-tool workflow report. See [the bounded workflow](bounded-task-skill-agent.md) for the subsequent implementation and acceptance evidence.

**Not ready to promise reliable automatic retention with a small model choosing
all tool calls.** Local work only; no commit, push or publication. Base:
`9e486d18fc27752b8dc9ee6be0150bdbb76a351b`, `/home/aeon/Projects/ROMS`.
Evidence root: `/home/aeon/.codex/benchmarks/roms-agent-trial/`.

## Current implementation improvements

- Outdated candidates retain their original user constraints in metadata while
  their procedure body stays withheld. This lets revisions preserve restrictions.
- MCP advertises explicit packet, source, cited-entry, draft and question shapes.
  Extra/quoted field names are rejected; string arguments remain compatible. Live
  source and bounded contract validation remain authoritative.
- `prepare_task_skill(..., retain=true)` supplies explicit save guidance without
  writing anything. Default preparation remains validation-only. Retention does not
  change the evidence packet or bypass MCP write policy.
- The optional retaining companion opts into this route and looks up candidate IDs
  and evidence instead of asking the user for metadata already available in ROMS.

## Evidence and limits

Current focused suite: **47 passed**, exit 0, `retaining-final-focused.log`.
Current native MCP lifecycle: **11 calls passed**, exit 0,
`typed-native-1/summary.json`; this uses scripted authored content and real ingestion.
These cover typed/string inputs, unknowns, source changes, profile policy, idempotency,
revision lineage and observations. They do not establish model reliability.

The latest broad run before the typed schemas and retention-routing addition was
**1,183 passed, 79 skipped, 9 warnings, 49 subtests**, exit 0, 142.28 seconds,
`revision-full.log`. A new full run is still required after the next implementation
step. Earlier broad results must not be presented as current complete validation.

Real-model findings:

| Trial | Result | Scope |
| --- | --- | --- |
| `real-companion-revision-3` | Passed | Replayed a prior generated seed, then real Gemma tool selection reused and revised it after source updates. New reviewer/nonblank requirements, exact original constraints, parent link, stale withholding and no inherited feedback were manually checked. This predates the latest tool-schema changes. |
| `real-companion-conflict-1` | Stopped without saving | Retrieved both opposing sources and asked correct precedence questions. It did **not** call finalization for those questions. The original loose `conflict_abstention` marker check was insufficient and has been removed; database state and manual transcript review support only the stated result. |
| `real-companion-task-1` | Failed retention | An ordinary procedure request produced validation but no save. |
| `real-companion-task-2` | Failed tool arguments | Malformed nested tool arguments; no saved candidate. |
| `real-companion-all-1` | Failed retention | Typed arguments validated, but the model claimed a save after only finalizing. Database verification caught the false claim. |
| `real-companion-all-2` | Failed tool arguments | Explicit retention routing selected save, but native tool arguments were malformed; no save. |
| `real-companion-nanbeige-1` | Failed workflow | Asked for available evidence/extra context instead of retrieving it; no saved candidate. |

Gemma used the previously verified E4B Q4 file with llama-server build 11115,
16,384 context, one slot, Vulkan offload, reasoning enabled with budget 512. Earlier
reasoning-off revision trials asked for IDs instead of searching. Nanbeige used the
existing 3B Sakura GGUF, ChatML template, reasoning off, same context and slot count.
Both servers were stopped after testing. No generated report review was executed.

Runtime inspection explains part of the Gemma failure. Local llama.cpp
`common/parsers/gemma4.cpp` defines a native dictionary grammar and explicitly does
not derive that grammar from the supplied tool parameter schema. Its dictionary
keys allow quotation characters; `common/chat-peg-parser.cpp` wraps/escapes those
key names into JSON without interpreting surrounding JSON quotes. This matches
observed keys such as `"\"task\""`. Explicit ROMS schemas reject that malformed
input but cannot fix the runtime's generation grammar. Do not weaken validation or
silently repair model arguments to hide this failure.

## Next implementation gate

Use a bounded ROMS-controlled authoring workflow rather than relying on the small
model to choose every persistence call. Reuse the proven controlled authoring
sequence in `scripts/verify_task_authoring.py`: retrieve current evidence, ask the
local model for a constrained assessment and draft, validate against current sources,
and save only when the caller opted into retention. Return persistence facts from
the database, never from model prose. Keep tool-execution authority separate.

Acceptance still needs ordinary-task creation/retention, reuse, revision after new
evidence, and conflict/missing-input refusal on the final implementation. Preserve
source citations, original constraints, immutable lineage and revision-specific
feedback. Generated procedures remain candidates, not certified task outcomes.
Publication stays deferred for discussion with the user.
