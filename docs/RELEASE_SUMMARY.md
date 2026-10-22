# ROMS 1.4 — Give your AI the context it is missing

Stop rebuilding the same context in every chat. ROMS turns your local documents
into searchable evidence, portable task briefs and reusable skill candidates.

**Try this:** import a project guide and troubleshooting notes, search for the
problem you're solving, and select the useful passages. Add your task and constraints,
preview the brief, and paste it into your preferred assistant. Your next conversation
starts with relevant sources already attached.

## New in 1.4

- **Portable task briefs:** collect up to eight search passages across queries,
  add your task and constraints, and copy or download a cited Markdown snapshot.
  No generation model is required to assemble the export.
- **Task-specific skill authoring:** an optional local agent can assess evidence,
  draft, review and retain a procedure for the task at hand.
- **Reuse that respects changing knowledge:** matching current evidence can reuse
  a saved candidate without generation; changed sources withhold stale bodies.
  Revise by name or ID while keeping original constraints and parent links.
- **Questions before another draft:** detected contradictions and missing essential
  inputs stop authoring without saving a candidate. Source references help you
  locate the requirements that need clarification.
- **Separate drafting and retention:** choose a read-only companion or opt into
  local candidate saving. Revision-specific feedback records observations without
  declaring a task verified.
- **Consistent ROMS/Buzburg branding:** refreshed README, launcher, HUD, chat and
  voice labels. Required dependency names and license notices remain intact.

## Start with your own knowledge

[Set up the local workspace](../README.md#add-knowledge-in-your-browser),
[build your first task brief](task-briefs.md), or
[connect the optional local skill agent](../examples/docker-agent/README.md).

ROMS runs search, embeddings and OCR locally after setup. You decide what to share
with another assistant. Source downloads require setup and do not bundle models
or compiled native artifacts.

Generated skills remain candidates for human review. Model review can miss errors;
source citations are not proof of correctness. Briefs are selected excerpts, not
complete documents, and exported snapshots do not automatically update. Neither
feature executes the procedures it prepares.

See [1.4 verification](verification/release-1.4.md) and
[real-model skill workflow evidence](verification/bounded-task-skill-agent.md).
