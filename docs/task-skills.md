# Skills created for the task at hand

The new authoring path starts with what the user wants to accomplish. ROMS retrieves
relevant knowledge; the connected agent's model turns that evidence into a tailored
procedure; ROMS checks the structure, citations and current source identity. The
result is a task-specific candidate for review before use within the user's
existing authorization. A skill need not already exist in the imported documents.

This differs from `knowledge_skills`: that feature extracts existing procedural
sections during import. Task skills can combine descriptive information from
multiple documents and adapt it to explicit task constraints. ROMS itself does not
call a generation model in this path. The author is the connected agent, using its
normal model and tool calls.

## Agent workflow

1. Call `prepare_task_skill(task, constraints)` before a multi-step task that needs
   domain knowledge. This uses ROMS's existing adaptive local search.
2. Perform the returned `assessment` as a separate model step before drafting: check
   source compatibility, relevance and missing inputs. If insufficient,
   author `{"status":"needs_information","questions":["What is missing?"]}`.
   Otherwise author the returned JSON contract:
   applicability, exclusions, cited prerequisites, ordered steps, result checks
   and unresolved questions.
3. Review the draft against the packet: check for opposing requirements, questions
   already answered by the user, actions misplaced as prerequisites, and prohibitions
   omitted from the relevant step. Correct it or abstain. A second model pass can help,
   but is not an independent verifier.
4. Call `finalize_task_skill(packet_json, skill_json)`, passing the unchanged
   evidence packet and the authored JSON. Both tools are available in the read-only
   MCP profile. Finalization creates no database row or installed file.
5. If finalization returns `needs_information`, resolve the questions and prepare
   again with the clarified task and constraints. No skill is exported in this state.
   This also applies when a full draft contains any nonempty `unknowns` list.
6. For a candidate, complete its review checklist before use and independently check
   actual results. `execution_ready` is always false: ROMS does not certify execution.
   Its Markdown is portable `SKILL.md` content that can be explicitly
   saved with the client's file tools. It is not an authorization to execute actions.

The optional Docker Agent example now includes this workflow in its root agent
instructions. Other MCP clients can use the same two tools; no Docker dependency
or deprecated server-initiated sampling is required. An MCP server cannot force an
arbitrary client to invoke its tools: the client needs this workflow instruction.

## What is checked

- Required authoring sections and bounded input/output.
- A supplied source ID for every prerequisite, step and check.
- Exact indexed content, source checksum and chunk identity at finalization.
- Source edits, deletion or client alteration reject a stale packet.
- Parent prerequisites remain present because each included source contains its
  complete indexed text, not just its matching child section.

These checks do not prove that a model's statement follows from the cited text.
They do not prove relevance, completeness, task success or safety. The response is
explicitly a **candidate**, and unknowns remain visible. Invalid authoring produces
an error for the agent to repair; there is no silent fallback to a fake generated skill.
The unknowns gate can withhold a model's acknowledged gaps, but cannot detect an
omission the model fails to acknowledge. Review remains necessary even with an empty
unknowns list. Review the original task and constraints in the packet/export alongside
the draft body; the model may omit a condition that the original constraints retain.
Prerequisites belong before the first action; later validation belongs
in steps/checks, with source ordering and prohibitions preserved.

## How additional knowledge helps

Every preparation retrieves from the current index, so new relevant information
can support a different procedure on the next task. No saved task skill is reused
silently. Candidates can now be saved explicitly and revised with parent links;
feedback stays on each exact candidate. ROMS does not automatically learn from
outcomes or promote revisions. Those require independently evaluated task results.

Retrieval considers eight ranked passages, then includes up to four distinct source
documents within a shared 16,000-character indexed-text budget. Oversized documents
are omitted whole, with their IDs reported. This preserves context for included
documents but limits coverage for large books. No-source results explicitly abstain.
The response reports retrieved and omitted coverage; it does not claim exhaustive
library search. More data alone is not a guarantee of better instructions.
Search uses the first 32 distinct word tokens of at most 128 characters from the
task followed by its constraints, matching the search engine's bounds. The complete
task and constraints remain in the authoring packet. Coverage reports the actual
query and whether it was reduced; constraints late in a long request may therefore
not affect retrieval. Rephrase the task if the retrieved evidence misses its focus.

Source material is returned to the connected client, just as with ordinary search.
Whether the model is local or remote depends on that client's configuration.

## Saving and reusing a candidate

The local MCP profile exposes `save_task_skill(packet_json, skill_json, parent_id)`.
Pass the same evidence packet and authored JSON used for finalization. Saving checks
sources and stores the candidate in one transaction; unresolved questions cannot be
saved. Repeating the same save returns the existing immutable ID. It does not install
a file, execute a procedure, or remove the requirement to review it.

Use `search_saved_task_skills(query)` and `get_saved_task_skill(skill_id)` in either
MCP profile. Search matches up to twelve title/task terms and includes stale records
in its count and pages. Reading revalidates the indexed sources. Changed or deleted
sources produce `status: stale` with metadata only, withholding the skill body and
export. Compare the saved task and constraints with the current request; changed
inputs require a new preparation, even when the sources are unchanged.

To improve a candidate, prepare with current evidence, author/review a replacement,
and save it with the old candidate's `parent_id`. The old record remains unchanged.
`record_task_skill_feedback(skill_id, outcome, event_id, note, evidence)` accepts
`helpful` or `needs_work` observations. Use a stable event ID for retries. Notes and
evidence references are self-reported text; ROMS does not execute or independently
verify them, and feedback never transfers to a new candidate or grants verified status.

`forget_task_skill` removes one saved candidate and its observations. It requires the
local profile and the existing destructive-tool opt-in. Descendants remain and retain
only the parent's identifier as a lineage reference. Source documents and installed
files are unaffected. Saved authored text can contain information derived from sources:
deleting a source makes the saved candidate unavailable, but does not erase its stored
authored text. Forget the candidate to remove that retained record.

The default Docker Agent example remains read-only and can search/read saved candidates.
To enable retention in a client, select the local profile and explicitly expose
`save_task_skill` and `record_task_skill_feedback` alongside its read tools. Keep deletion
disabled unless needed. The current workflow does not silently save every model response.

## Verification

`tests/test_task_skills.py` exercises source context, stale/deleted/tampered packets,
missing/invalid citations, output structure, budget omission, new knowledge and MCP
dispatch. `scripts/verify_docker_agent.py` additionally exercises preparation and
finalization through the real standalone Docker Agent and native ROMS MCP server,
using a scripted model endpoint. That integration test verifies transport and
contracts, not a local model's ability to write good skills.

`tests/test_task_skill_store.py` covers persistence, live source invalidation, lineage,
idempotent feedback, deletion, source-writer races and MCP policy. Run the native storage
integration with `scripts/verify_saved_task_skills.py --output /absolute/new/results`.
It uses scripted authored JSON, real ingestion and a temporary native MCP database;
it does not repeat the generation-model evaluation.

`scripts/verify_task_authoring.py` tests actual local model generation between native
MCP preparation and finalization. It uses temporary databases, real local retrieval,
seven synthetic cases, and a loopback OpenAI-compatible endpoint. The default disables
reasoning through `chat_template_kwargs.enable_thinking` and requests JSON output
constrained by the returned `response_schema`; the serving runtime must support
JSON-schema output and the thinking option. These are optional client capabilities;
the MCP tools themselves do not require a particular generation runtime. Example:

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/python scripts/verify_task_authoring.py \
  --endpoint http://127.0.0.1:8080/v1 --model your-local-model \
  --output /absolute/path/to/new-results-directory
```

The script invokes the two MCP tools in a fixed sequence, with separate model evidence
assessment, drafting and review passes between them. A blocking assessment skips
drafting and goes straight to abstention. It tests authoring and
abstention, not autonomous tool selection or execution. It retains raw requests,
responses (including the initial draft), source packets and results. Automated keyword signals help spot regressions;
they do not replace manual semantic review. No generated procedure is executed.
Use `--suite holdout --seed 17` for the two additional scenarios, or `--case ID`
to diagnose one case. The default seed is 42. The script refuses to certify a run
whose tracked source/fixture hashes changed during execution.

The tested Gemma 4 E4B Q4 configuration passed the final nine scenarios. This is
bounded local acceptance evidence, not a guarantee for arbitrary documents or models.
See the [readiness report](verification/task-skills-release-readiness.md) for exact
runtime settings, results, earlier failures and manual review limits.

## Existing extracted drafts

The section extractor now retains text from ancestor headings, including prerequisites
above a child Steps section. It excludes sibling sections and omits a draft if parent
context makes it exceed the budget. To update drafts already stored before this change,
use the Skills refresh control or `refresh_knowledge_skills` in the local MCP profile.
This rebuilds from indexed text; it does not download models or activate skills. Inspect
the complete source before execution: sibling validation sections can still be separate
from an extracted draft. Task-time authoring includes complete documents within its budget.

## Optional retaining companion

The Docker Agent example `examples/docker-agent/roms-retain.yaml` opts into saving
reviewed candidates and recording observations. Its tool allowlist exposes only
ROMS tools; it does not execute the generated procedure. The original `roms.yaml`
remains read-only. See the example README for local runtime configuration and
isolated real-model verification.

For `finalize_task_skill` and `save_task_skill`, prefer JSON objects in the
`packet_json` and `skill_json` arguments. Strings remain supported for existing
clients. Pass only the returned `packet` object, without the surrounding assessment
or schema fields. Both forms go through the same bounded source and contract checks.

When revising an outdated candidate, its metadata still provides the original task
and user constraints. The old procedure body remains withheld. Retrieve current
evidence for that task, preserve the constraints, and link the new saved candidate
with `parent_id`. Old feedback belongs to its original revision and does not certify
the new one.

## ROMS-controlled authoring workflow

The optional workflow removes nested tool-argument copying and persistence decisions
from the model. Configure a local OpenAI-compatible generation endpoint supporting
JSON-schema responses in the MCP server environment:

```sh
export ROMS_AUTHORING_ENDPOINT=http://127.0.0.1:8080/v1
export ROMS_AUTHORING_MODEL=your-served-model-name
```

Use your existing ROMS MCP launch configuration. The endpoint must use a numeric
loopback IP, an explicit port, HTTP, and the `/v1` path. Redirects and environment
proxies are disabled. ROMS does not download or start a generation model.

- `draft_task_skill(task, constraints)` assesses, drafts, reviews and validates a
  candidate without retaining it. It is available under the read-only profile.
- `create_task_skill(task, constraints)` performs the same workflow and retains a
  valid reviewed candidate. It requires the local write profile.
- `revise_saved_task_skill(skill)` accepts an ID or an unambiguous name and rebuilds
  from current evidence while preserving
  the original task and constraints and linking the result to its parent. It also
  requires the local write profile. Ambiguous matches return choices without generation
  or a write. An unchanged revision reuses the existing candidate without self-linking.

ROMS makes at most three generation requests: evidence assessment, drafting, and
review. A blocker stops the workflow without saving. Responses must finish, fit
within the response budget and match the contract. Source identity is checked again
before the atomic save. Cancellation during generation does not save a draft.

For creation, ROMS first retrieves current evidence. It reuses a retained candidate
only when the request and evidence revision match and it has no `needs_work` feedback.
Newly retrieved documents therefore prevent reuse of an older evidence packet.
`model_called=false` means no **generation** call was needed; retrieval may still
use embeddings. Coverage remains bounded to the retrieved documents.

A model review is not independent verification. Candidates keep the original user
constraints and are not installed or executed. Read persistence from the returned
`persisted` field and ID, not an assistant's prose. The retaining companion example
is `examples/docker-agent/roms-agent.yaml`; it uses this workflow while the older
`roms-retain.yaml` remains a manual-tool-chain experiment. Use
`roms-agent-readonly.yaml` for drafting without retention. Blocker responses include
source references so users can locate the evidence behind the questions.
