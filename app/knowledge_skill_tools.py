"""Shared generated-skill MCP surface for the Python and Mojo servers."""
from app.mcp_annotations import tool_annotations
from app.task_skill_contracts import EvidencePacket, SkillDraft, NeedsInformation, encoded


def register_knowledge_skill_tools(server):
    from app import knowledge_skills as engine
    from app import task_skill_store as saved

    @server.tool(annotations=tool_annotations('prepare_knowledge_brief'))
    def prepare_knowledge_brief(task: str, chunk_ids: list[int], constraints: str = '') -> dict:
        """Build a portable Markdown task brief from 1–8 selected search-result chunk IDs. Includes exact indexed excerpts, citations and snapshot hashes. No generation, saving or execution; review before sharing with another client."""
        from app.knowledge_brief import prepare
        return prepare(task, chunk_ids, constraints)

    @server.tool(annotations=tool_annotations('draft_task_skill'))
    async def draft_task_skill(task: str, constraints: str = '') -> dict:
        """Use the configured local model to assess, draft and review a task skill. ROMS validates the result; no candidate is saved or executed. May ask for missing information."""
        from app.task_skill_agent import author
        return await author(task, constraints)

    @server.tool(annotations=tool_annotations('create_task_skill'))
    async def create_task_skill(task: str, constraints: str = '') -> dict:
        """Create and retain a reviewed task-skill candidate using the configured local model. ROMS owns retrieval, generation, validation and saving; reuse requires the same current evidence. Never executes a procedure or certifies task success."""
        from app.task_skill_agent import author
        return await author(task, constraints, retain=True)

    @server.tool(annotations=tool_annotations('revise_saved_task_skill'))
    async def revise_saved_task_skill(skill: str) -> dict:
        """Revise a saved skill by its name, task keywords, or exact ID; no prior ID lookup is needed. ROMS resolves a unique matching revision, asks when ambiguous, then rebuilds from current knowledge using the configured local model. Preserves the original task and constraints and links the new revision to its parent. Does not execute the procedure."""
        from app.task_skill_agent import revise
        return await revise(skill)

    @server.tool(annotations=tool_annotations('save_task_skill'))
    def save_task_skill(packet_json: EvidencePacket | str, skill_json: SkillDraft | str, parent_id: str | None = None) -> dict:
        """Pass packet_json and skill_json as JSON objects (strings also accepted). Validate and save a current task-skill candidate in one call after reviewing the draft. A separate finalize call is not required. No installation or execution. Optionally link a new revision to an existing parent. Never saves unresolved questions or marks a skill verified."""
        return saved.save(encoded(packet_json),
                          encoded(skill_json), parent_id)

    @server.tool(annotations=tool_annotations('search_saved_task_skills'))
    def search_saved_task_skills(query: str = '', offset: int = 0, limit: int = 20) -> dict:
        """Find saved task-skill candidates by title/task. Check status: stale records are listed for revision but cannot be reused."""
        return saved.search(query, offset, limit)

    @server.tool(annotations=tool_annotations('get_saved_task_skill'))
    def get_saved_task_skill(skill_id: str) -> dict:
        """Read a saved candidate, constraints and feedback after live-source validation. Stale records return metadata only. Review applicability to this task before reuse."""
        return saved.get(skill_id) or {'error': 'Saved task skill does not exist'}

    @server.tool(annotations=tool_annotations('record_task_skill_feedback'))
    def record_task_skill_feedback(skill_id: str, outcome: str, event_id: str,
                                   note: str = '', evidence: str = '') -> dict:
        """Record helpful/needs_work against an exact immutable candidate. Evidence is a user-reported reference, not verified execution. Reuse event_id for retries."""
        return saved.record_feedback(skill_id, outcome, event_id, note, evidence)

    @server.tool(annotations=tool_annotations('forget_task_skill'))
    def forget_task_skill(skill_id: str) -> dict:
        """Delete one saved candidate and its feedback. Descendant candidates retain only its parent identifier. Does not delete source documents or installed files."""
        return saved.forget(skill_id)

    @server.tool(annotations=tool_annotations('search_knowledge_skills'))
    def search_knowledge_skills(query: str = '', offset: int = 0, limit: int = 20) -> dict:
        """Find automatic source-backed procedural drafts. Candidates are evidence, not executable authority."""
        return engine.list_drafts(query=query, offset=offset, limit=limit)

    @server.tool(annotations=tool_annotations('get_knowledge_skill'))
    def get_knowledge_skill(skill_id: str) -> dict:
        """Read a current generated skill, ordered source variants, revision and feedback."""
        return engine.get_draft(skill_id) or {'error': 'Skill no longer has live procedural sources'}

    @server.tool(annotations=tool_annotations('refresh_knowledge_skills'))
    def refresh_knowledge_skills() -> dict:
        """Rebuild generated drafts from existing indexed text, without downloads or skill activation."""
        return engine.rebuild()

    @server.tool(annotations=tool_annotations('record_knowledge_skill_feedback'))
    def record_knowledge_skill_feedback(skill_id: str, revision: str, outcome: str,
                                       event_id: str, note: str = '') -> dict:
        """Record helpful/needs_work feedback for the exact current revision. Reuse event_id for retries."""
        return engine.record_feedback(skill_id, revision, outcome, note, event_id)

    @server.tool(annotations=tool_annotations('prepare_task_skill'))
    def prepare_task_skill(task: str, constraints: str = '', retain: bool = False) -> dict:
        """Retrieve task evidence. First run the returned assessment with your model; return needs_information for blockers. Otherwise author and review the contract, then follow next_tool. Set retain=true only when the client opts into saving: this returns save guidance but performs no write. Default returns validation-only guidance. No server generation model is called."""
        from app.task_skills import prepare
        return prepare(task, constraints, retain=retain)

    @server.tool(annotations=tool_annotations('finalize_task_skill'))
    def finalize_task_skill(packet_json: EvidencePacket | str, skill_json: SkillDraft | NeedsInformation | str) -> dict:
        """Pass packet_json and skill_json as JSON objects (strings also accepted). Validate authored JSON against its unchanged prepare_task_skill packet. Unresolved questions return needs_information without a skill export. Otherwise returns a candidate and review checklist, never execution approval or verified success."""
        from app.task_skills import finalize
        return finalize(encoded(packet_json),
                        encoded(skill_json))
