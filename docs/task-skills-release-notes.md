# Task-skill release notes: skills for the task at hand

ROMS can help your local agent turn indexed knowledge into a procedure tailored to
the task you're doing. The agent retrieves evidence, checks whether it is sufficient,
drafts a cited skill, and reviews it before ROMS validates the result.

- **Task-specific procedures:** combine relevant information across documents instead
  of relying only on procedures that already exist in your library.
- **Questions before guesswork:** unresolved questions produce a needs-information
  response, with no skill export. The client workflow separately checks evidence
  compatibility before drafting.
- **Traceable drafts:** each candidate carries source identity, a review checklist,
  and portable SKILL.md text. Changed or deleted sources invalidate old packets.
- **Reusable candidates:** save a reviewed draft, search it later, and link refinements
  to their parent. Live-source checks withhold stale bodies, while revision-specific
  feedback preserves what users reported without treating it as proof of correctness.
- **Better source context:** task authoring includes complete indexed documents within
  its budget; extracted procedures now retain conditions above child headings.
- **Local-model evaluation:** a repeatable trial exercises real local generation and
  the native MCP server using isolated fixture databases, including conflicting
  sources and hostile instructions embedded in a document.

This is a reviewed-drafting workflow. Models can still overlook contradictions or
invent requirements; a citation proves source identity, not that a claim follows
from it. Candidates are never certified execution-ready. The tools do not execute
procedures, install skills, or learn automatically from outcomes.

Existing installations should refresh extracted skills to incorporate ancestor
context. Task-authoring coverage is bounded and may omit oversized documents.
See [the workflow and limits](task-skills.md) before configuring a client.

Included in the ROMS 1.4 update. The new bounded
workflow lets ROMS handle assessment, generation, review and saving through one
creation call. A separate read-only profile drafts without retaining anything.
Revision accepts a saved name or ID and asks for a choice when matches are ambiguous.
Current evidence can reuse an existing candidate without another generation call;
changed knowledge triggers a new assessment and linked revision.

See [bounded workflow verification](verification/bounded-task-skill-agent.md) for
current checks and limitations. Earlier manual-tool companion trials exposed unreliable
retention and malformed arguments; those experimental examples remain documented
separately. The new workflow reduces the decisions left to the companion but does
not make generated procedures independently verified.
