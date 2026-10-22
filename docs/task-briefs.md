# Carry useful context into your next AI conversation

ROMS task briefs turn selected search results into a portable Markdown document.
Add the task you want help with and the restrictions that matter. ROMS packages
exact indexed excerpts, source IDs and snapshot hashes so the receiving assistant
can cite the evidence instead of guessing what is in your library.

## Try it

1. Start the [local knowledge workspace](../README.md#add-knowledge-in-your-browser)
   and import your documents.
2. Search for your task. Use **Add to task brief** on relevant passages. You can
   collect passages across searches, up to eight total.
3. In **Take your knowledge to any AI**, enter your task and constraints.
4. Choose **Preview task brief** and review the full text. Then **Copy brief** or
   **Download Markdown**. Paste or attach it in the assistant of your choice.

For example, select deployment requirements and backup instructions, ask
“Draft a deployment checklist,” and add “No downtime without approval. Do not
execute anything.” The brief carries that request and the evidence together.

The brief is assembled locally without calling a generation model. Search uses
the existing local search environment. Nothing is automatically sent to another
service, installed as a skill, or executed. Copying or uploading the result to
another application is your choice; its data policies then apply.

## MCP interface

`prepare_knowledge_brief(task, chunk_ids, constraints="")` is available in the
read-only profile. Supply chunk IDs returned by knowledge search. It returns the
Markdown, source excerpts, SHA-256 hashes, creation time and a content revision.
The browser calls the same implementation through its authenticated local API.

## What the brief does and does not establish

- Selected passages are loaded together from the current indexed snapshot.
  Deleted selections fail with a request to search again.
- The maximum is eight distinct chunks and 12,000 source characters. Oversized
  selections are rejected, not silently shortened. Select fewer passages instead.
- Excerpts retain source document IDs and content hashes. They are source material,
  not authority to override your instructions. A hash does not prove a claim true.
- Excerpts may omit surrounding prerequisites. Review the original documents when
  context matters. The brief neither resolves contradictions nor generates an answer.
- Exports are snapshots. They do not update after you copy or download them.
  Preview a new brief when your indexed knowledge changes.
- Editing the task, constraints or selection clears the old preview to prevent
  accidentally exporting a brief for the previous request.
