"""Shared generated-skill MCP surface for the Python and Mojo servers."""
from app.mcp_annotations import tool_annotations


def register_knowledge_skill_tools(server):
    from app import knowledge_skills as engine

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
