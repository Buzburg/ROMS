# Skills that grow with your knowledge

ROMS now turns indexed procedural guides and checklists into source-backed skill
drafts automatically. Import a backup guide, deployment runbook, or troubleshooting
checklist: the same transaction that updates search also extracts its procedures.
No additional model service, account, or network connection is needed for drafting.

## What grows as you add information

- New procedural topics create new drafts.
- Matching descriptive section headings collect additional source procedures.
- Different procedures remain ordered, separately cited variants. ROMS does not
  silently blend contradictory instructions.
- Identical procedural text is deduplicated in the preview; copies are counted
  separately from unique variants.
- Source changes produce a new revision. Feedback from the previous revision stays
  in history and does not endorse the new one.
- Removing an indexed source removes it from current drafts. A draft disappears
  when it has no remaining live sources.

This expands coverage and supporting evidence. More files do not automatically
mean better instructions: duplicates add no unique procedure, and irrelevant or
incorrect material can reduce usefulness. Feedback is user-reported evidence,
not a benchmark score or proof that a procedure is safe.

## Use it in the local knowledge workspace

Run `python roms.py knowledge` in your installed environment (or use `pixi run
python roms.py knowledge`). The **Skills from your knowledge** panel lets you:

1. Find a draft by task keywords.
2. Review its procedural variants, prerequisites and source references.
3. Open every contributing indexed chunk.
4. Export a reviewable `SKILL.md` with a revision and source checksums.
5. Mark that revision **helpful** or **needs work**, with an observation.

New imports create drafts automatically. Starting the knowledge workspace or the
Python MCP server also backfills an existing index. **Generate from existing
knowledge** provides an explicit retry/backfill action without re-running embeddings.

## CLI

```sh
python roms.py skills refresh
python roms.py skills list --query "database backup"
python roms.py skills show knowledge-REPLACE_WITH_ID
python roms.py skills export knowledge-REPLACE_WITH_ID --revision REVISION --output SKILL.md
python roms.py skills feedback knowledge-REPLACE_WITH_ID --revision REVISION --outcome helpful --event-id my-task-001 --note "Restore check passed in staging"
```

Use the ID and revision returned by `list` or `show`. Put `--db /path/to/index.db`
before the subcommand to use a specific existing index. Export refuses stale
revisions and existing output files. It does not install the skill into an agent.
Exported files are snapshots; check their revision before reuse.

## MCP

Both MCP servers register these tools:

| Tool | Purpose | Default read-only profile |
| --- | --- | --- |
| `search_knowledge_skills` | Find current drafts by keywords, with pagination | Allowed |
| `get_knowledge_skill` | Read current ordered variants, references and feedback | Allowed |
| `refresh_knowledge_skills` | Backfill drafts from the existing index | Requires the local profile |
| `record_knowledge_skill_feedback` | Record a helpful/needs-work observation against a revision | Requires the local profile |

A client can discover a relevant draft, inspect its cited evidence and decide
whether its procedure applies to the user's task. Generated drafts never grant
permission to execute commands. Manual skills and trajectory-derived candidates
remain separate and are not overwritten. Native-server users upgrading an old
index can run the CLI refresh before starting, or use the refresh tool with the
local profile. Newly ingested documents need no separate refresh.

## Extraction and limits

The first implementation is deterministic extraction, not free-form synthesis or
model training. It recognizes structured lists with at least two items and an
English procedural verb, keeps surrounding text in the section, and groups by
normalized heading. Generic headings such as “Setup” are scoped to the document
title. Descriptive text without a recognizable procedure produces no skill.

At most 32 procedures are extracted per document. Sections over 12,000 characters,
over 64 list items, or with headings over 240 characters are skipped rather than
clipped into apparently complete instructions. The detail/export preview includes
up to 32 source records and reports omitted records. All live records participate
in the revision hash, including omitted records. Search uses bounded keyword
matching, not semantic skill ranking. Large backfills hold a database writer lock;
run them outside heavy import sessions when practical.

Sources can be incomplete, malicious or contradictory. Every generated artifact
is visibly marked as a candidate; source text is quoted, not executed or promoted
to trusted instructions. Review applicability, prerequisites, licensing and
validation before using or sharing an exported skill. Imported material is not
uploaded by this feature. Your connected AI client's data-sharing behavior remains
under that client's configuration.

## Verification

`python scripts/verify_knowledge_skills.py` exercises real local embedding and
native parsing through ingestion, automatic drafts, retrieval, additional source
variants, revision-specific feedback, export and deleted-source removal in a
throwaway database. The unit/integration suite additionally covers rollback,
source citations, duplicate evidence, pagination, HTTP authentication, stale export
rejection, non-overwriting CLI output and MCP policy.

Design references and archive review boundaries are recorded in
[reference review](reference-review.md). No upstream agents or installers are run
by this feature, and no third-party implementation was copied.
