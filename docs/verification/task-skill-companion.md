# Retaining companion: real local-model verification

Historical manual-tool workflow report. See [the bounded workflow](bounded-task-skill-agent.md) for the subsequent implementation and acceptance evidence.

Historical checkpoint. See [current automatic-task readiness](task-skill-agent-readiness.md)
for later ordinary-task failures, schema changes and the next acceptance gate.

Local work against base `9e486d18fc27752b8dc9ee6be0150bdbb76a351b` in
`/home/aeon/Projects/ROMS`. Nothing committed, pushed or published.
Evidence root: `/home/aeon/.codex/benchmarks/roms-agent-trial/`.

## Change and acceptance

`examples/docker-agent/roms-retain.yaml` exposes nine ROMS tools under the local
profile, with destructive tools disabled. Its instructions cover evidence preparation,
review, saving candidates, revision links and evidence-qualified observations. The
original example remains read-only. Neither exposes procedure execution tools.

Real-model trials exposed two problems. `real-companion-1` unnecessarily asked for
more “ROMS knowledge” despite retrieving a sufficient document. Instructions now
separate the underlying task from the request to create a reusable skill and clarify
that retrieved documents are the knowledge source. `real-companion-2` authored the
correct procedure but repeatedly appended contract fields to a serialized packet,
causing JSON “Extra data” errors. No candidate was saved in either failed run.

`finalize_task_skill` and `save_task_skill` now accept structured JSON objects as
well as strings. Both forms pass through the same bounded source/contract validator.
The companion explicitly passes only the returned packet object. No validation was
relaxed to accept malformed packets. `real-companion-3` then passed creation/saving.

## Completed evidence

- Full suite, `.venv/bin/python -m pytest -q`: exit 0, **1,183 passed, 79 skipped,
  9 warnings, 49 subtests passed**, 112.19 seconds. Log: `companion-full.log`.
  Uses compiled broker/sandbox paths, the project virtual environment and runtime
  library paths, and offline embedding cache, as in the lifecycle checkpoint.
- Focused lifecycle/authoring/policy suite: exit 0, 45 passed in 5.34 seconds.
  Log: `companion-structured-focused.log`. Tests both object and string arguments
  for validation and saves, including read-only and destructive-operation policy.
- `verify_saved_task_skills.py`: exit 0, 11 native MCP calls, structured save arguments
  and string revision compatibility; `saved-skills-objects-1/summary.json`.
- `verify_docker_agent.py`: exit 0, nine real MCP results per profile; string
  compatibility, saving/reopening/feedback, and server-enforced read-only denial.
  Final results: `retaining-companion-2/result.json`. Generation is scripted here.
- `verify_local_skill_agent.py`: exit 0, **real model with autonomous tool selection**,
  `real-companion-4/summary.json`. First session prepared, finalized and saved a
  candidate. A fresh session searched and read it without creating another or adding
  feedback. The verifier inspected the actual database, not just assistant claims.

Real-model command:

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/python scripts/verify_local_skill_agent.py \
  --agent /home/aeon/.codex/benchmarks/roms-agent-trial/docker-agent \
  --model gemma-local \
  --output /home/aeon/.codex/benchmarks/roms-agent-trial/real-companion-4
```

Runtime: standalone Docker Agent v1.152.0; llama-server build 11115, commit
`4d14afc58`; Gemma 4 E4B Q4 at the previously recorded local model path.
Model SHA-256: `85a896a047553e842f25297ee5b031d64ff30147d9c4af17b1e4b394cd1fab87`.

Server flags: `--host 127.0.0.1 --port 18973 -c 16384 -np 1 -ngl 99 --reasoning off`.
Model sampling: temperature 0, maximum 4,096 output tokens; agent maximum 12
iterations and 240 seconds per session. All documents and databases were disposable.
The model server was stopped after the trials.

Manual review of `real-companion-4/candidates.json` and `reuse.log`: the saved skill
retains title/date/author as required fields, PASS only when all three are present,
FAIL with missing fields otherwise, a supplied-report prerequisite, and the original
no-file-modification constraint. The fresh session accurately explained these rules.
Its candidate ID matches the earlier successful run. No report review was executed.

## Limits and next acceptance case

This proves a small report-review workflow, not general agent reliability or
independent semantic verification. Search/read happened in the reuse session; the
creation session went directly to preparation. Separate evidence assessment was not
independently enforced or graded in this autonomous trial. Previous nine-case
controlled authoring evidence remains distinct from autonomous tool-selection tests.

Next: update indexed evidence, ask the real companion to revise the saved skill, and
verify new source requirements, parent lineage, stale withholding and feedback
isolation. Automatic improvement from independently verified task outcomes remains
unfinished. Publication remains deferred for user discussion.
