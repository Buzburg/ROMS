# Optional Docker Agent companion

## Bounded task-skill workflow

Use `roms-agent.yaml` to create and retain candidates from ordinary task requests,
reuse current candidates, and revise them by name after knowledge changes. ROMS owns
evidence assessment, drafting, review and atomic persistence. The outer agent supplies
the task and constraints; it does not assemble nested persistence arguments.

Set `ROMS_AUTHORING_ENDPOINT` to your local OpenAI-compatible generation server
(for example `http://127.0.0.1:8080/v1`) and `ROMS_AUTHORING_MODEL` to its served model
name. The server must support JSON-schema responses; the companion model must also
support tool calls. Configure the ROMS runtime/data variables listed below, then run:

```sh
/path/to/docker-agent run examples/docker-agent/roms-agent.yaml --exec --safety restricted \
  "Prepare a report-review procedure from my indexed requirements. Do not execute it."
```

Choosing this profile enables saving candidates. For drafting without writes, choose
`roms-agent-readonly.yaml`, which uses ROMS's read-only policy. Neither profile exposes
procedure execution. Review the returned candidate and its original constraints before
use; model review does not prove correctness. See the
[bounded workflow verification](../../docs/verification/bounded-task-skill-agent.md).

## Earlier transport and manual-tool experiments

The standalone Docker Agent v1.152.0 binary successfully called the compiled ROMS
MCP server through local stdio. The integration test used scripted model responses,
real native parsing and local embeddings, and a throwaway ROMS database. It verified
search, cited skill detail, a denied feedback write in the read-only profile, and a
persisted feedback write in the local profile. The extended trial also prepares
task evidence, finalizes a scripted contract, saves it, searches and reopens it,
and records revision-specific feedback. The local trial uses the retaining
companion template; the read-only trial deliberately advertises write tools to
verify that ROMS denies them at the server boundary.
It did not execute a procedure or
measure a real generation model's reasoning.

## Reproduce the transport test

With ROMS dependencies, its public embedding cache, and `build/roms-mcp` available:

```sh
.venv/bin/python scripts/verify_docker_agent.py \
  --agent /absolute/path/to/docker-agent \
  --output /absolute/path/to/trial-results
```

The test starts a loopback model-response fixture and isolates ROMS data and agent
sessions in a temporary directory. It disables Docker Agent telemetry and automatic
tool installation. The fixture exercises nine ROMS tool calls per profile. Automatic approval is used
only for these synthetic fixture calls; no shell/filesystem tool is exposed.
The output directory retains transcripts, synthetic requests and result JSON.
The temporary database and server are removed when the test finishes normally.

## Try a real local model

`roms.yaml` is a starter configuration for an OpenAI-compatible server listening
at `http://127.0.0.1:8080/v1`. Set `ROMS_AGENT_MODEL` to a tool-calling model served
there, or edit that local endpoint. A real-model report-review drafting, saving and fresh-session retrieval trial passed with Gemma 4 E4B Q4;
this is limited workflow evidence, not a general reliability guarantee.

Set these environment variables before launching the standalone binary:

- `ROMS_ROOT`: absolute ROMS checkout path with a compiled `build/roms-mcp`.
- `ROMS_AGENT_DB`: an existing indexed test database.
- `ROMS_AGENT_DATA`: writable test state directory.
- `ROMS_AGENT_KNOWLEDGE` and `ROMS_AGENT_SKILLS`: test source and manual-skill directories.
- `ROMS_PYTHON_PREFIX`, `MOJO_PYTHON_LIBRARY`, `PYTHONPATH`: the same project runtime
  settings used by the native ROMS server (the verification script demonstrates them).
- `TELEMETRY_ENABLED=false` and `DOCKER_AGENT_AUTO_INSTALL=false`.

Then run:

```sh
/path/to/docker-agent run examples/docker-agent/roms.yaml --exec --safety restricted \
  "Find the staging backup procedure and explain its prerequisites with citations."
```

Use `--data-dir /absolute/path/to/test-agent-state` to isolate agent sessions.
The read-only starter exposes extracted-skill search and reading, saved-task-skill
search and reading, task preparation, and finalization. Saving and feedback require
a client configured for the local write profile; see the task-skills guide.
Its instructions ask the agent to create a task-specific skill from the returned
evidence before knowledge-dependent multi-step work. See `docs/task-skills.md`. ROMS remains a separate MCP
service. Docker Agent is not a required ROMS dependency; a Docker daemon was not
needed for the tested standalone/local-stdio path. Docker container sandboxing was
not tested because this account cannot access the Docker daemon.

Before trying execution or skill rewriting, add repeatable task checks and define
which tools may change what. The current feedback endpoint accepts observations;
it does not independently prove success. Retrieval also needs review of the original
source. Ancestor prerequisites are now retained in extracted drafts after refresh,
but sibling validation sections may remain separate. Task-time authoring includes
complete indexed documents within its budget.

## Retain and refine useful drafts

**Experimental:** explicit skill-creation trials passed, but ordinary-task requests
have also failed to save or produced malformed tool calls. Do not trust a model's
claim that it saved a skill without the tool's persistence receipt. See
[the current readiness report](../../docs/verification/task-skill-agent-readiness.md).

Use `roms-retain.yaml` instead of `roms.yaml` to let the companion save reviewed
candidates and record observations in your ROMS database. It searches prior skills,
compares the task and constraints, prepares evidence, drafts and reviews a procedure,
and saves the resulting candidate. Refinements can link to the original candidate.
The tool allowlist does not expose shell execution, file editing or forgetting.
Reported feedback helps identify what to revisit; it does not certify success.

The retaining example uses the `local` MCP profile with destructive tools disabled.
Choosing it opts into candidate and feedback writes. It does not install generated
skills or execute their procedures. Keep the restricted client safety mode for
normal use. Automatic approval in the verification scripts applies only to isolated
synthetic data and the exposed ROMS tools.

To test autonomous tool selection against a running local model:

```sh
.venv/bin/python scripts/verify_local_skill_agent.py \
  --agent /absolute/path/to/docker-agent \
  --endpoint http://127.0.0.1:18973/v1 --model your-local-model \
  --output /absolute/path/to/new-results-directory
```

This uses a disposable report-review document, then asks a fresh agent session to
retrieve the saved candidate without creating another. It then updates the source
requirements and asks the agent to save a linked revision. Inspect `agent.log` and
`candidates.json` even if workflow checks pass: saving a structurally valid draft
is not proof that every instruction follows the source. No report review is executed.

For focused revision trials, `--seed-candidate /path/to/prior/candidates.json`
replays one previously generated candidate against the exact fixture instead of
regenerating it. Source identity and the candidate ID must still match. The verifier
labels seeded creation separately from real generation; reuse and revision still
use the real model and its own tool choices.

The retaining template sets `retain=true` during preparation so the returned next
step explicitly requests saving. Preparation itself never writes. Use `--scenario
all` in the verifier to exercise an ordinary procedure request, reuse, source-update
revision, and conflicting sources. The script checks actual saved records; its
transcript still needs manual semantic review. `--scenario task` and `--scenario
conflict` isolate those cases. Current failures are documented above.
