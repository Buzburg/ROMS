# Saved task-skill lifecycle verification

Local work against base commit `9e486d18fc27752b8dc9ee6be0150bdbb76a351b` in
`/home/aeon/Projects/ROMS`. This extends the authoring-preview checkpoint. No commit,
push or release was made. Publication remains deferred for discussion.

## Implemented contract

Candidates can be saved, searched, reopened, linked to parent revisions, given
revision-specific observations, and forgotten through MCP. Saves validate sources
inside the same SQLite write transaction. Reopening revalidates live sources and
withholds the skill body when evidence changes or disappears. Identical saves and
feedback events are idempotent. Feedback does not transfer to child revisions or
certify correctness. The default Docker Agent example remains read-only.

Stored manifests omit source document bodies. Authored text can contain derived
information and remains stored until forgotten; source deletion alone withholds
it from retrieval rather than erasing the record. Forgetting a parent preserves
its children and their parent identifier.

## Completed checks

Evidence directory: `/home/aeon/.codex/benchmarks/roms-agent-trial/`.

- Full repository suite: `.venv/bin/python -m pytest -q`, exit 0;
  **1,181 passed, 79 skipped, 9 warnings, 49 subtests passed**, 94.48 seconds.
  Log: `saved-skills-full.log`. Existing fork-related deprecation warnings remain.
- Focused lifecycle, authoring and MCP policy checks: 43 passed, exit 0.
  The subsequent full suite includes the final retry-after-parent-forgetting check.
  A competing SQLite writer is rejected while saving validates source identity.
- Native MCP lifecycle: `scripts/verify_saved_task_skills.py --output
  /home/aeon/.codex/benchmarks/roms-agent-trial/saved-skills-native-1`, exit 0;
  11 calls passed. Uses real local ingestion and embeddings, scripted authoring,
  and an isolated database. Checks persistence, retry deduplication, search,
  revision lineage, feedback isolation, stale withholding and forgetting.
- Actual generated artifact replay: `saved-skills-generated-replay.py`, passed.
  The previous Gemma 4 E4B Q4 backup draft and original packet were saved unchanged
  after reingesting their original fixture, then reopened with the same candidate
  ID and constraints. Summary: `saved-skills-generated-replay.json`.
  Generation was not repeated, and no generated task was executed.

The suite used the project virtual environment, compiled broker/sandbox paths,
Python library/runtime paths, and offline cached embeddings. The native verifier
sets its own isolated database and MCP runtime environment. Full source hashes
are retained in `saved-skills-final-manifest.json` in the evidence directory.
The earlier nine real-generation scenarios remain authoring evidence; this change
adds persistence and does not change the generation prompt or schema.

The subsequent [companion verification](task-skill-companion.md) covers structured
tool arguments and real-model creation/reuse, with the latest full-suite result.

## Remaining boundary

This is a reusable, reviewed-candidate workflow. Source identity and schema checks
are not proof that generated instructions follow the evidence. Observations are
self-reported. Automatic task execution, independently verified outcome learning,
automatic promotion, and a saved-skill UI are not implemented. The broader goal of
automatically improving skills from task outcomes is not complete.
