"""Typed MCP schemas around compiled Mojo callables; no generated Python source."""

from app.mcp_annotations import tool_annotations
from typing import Protocol
from fastmcp import FastMCP
from app.mcp_policy import MCPPolicy
from app.config import SKILLS_DIR
from app.safe_paths import markdown_path
from app.memory_tools import register_memory_tools

class NativeHandlers(Protocol):
    def pack_context(self, costs: list[int], utilities: list[int], budget: int, required: int) -> list[int]: ...
    def search_knowledge_base(self, query: str, limit: int) -> str: ...
    def create_support_ticket(self, ticket: str, email: str, summary: str) -> str: ...
    def get_support_ticket(self, ticket: str) -> str: ...
    def update_ticket_status(self, ticket: str, status: str) -> str: ...
    def list_support_tickets(self, status: str) -> str: ...

def build_server(native: NativeHandlers) -> FastMCP:
    server = FastMCP("ROMS-Mojo-Engine", middleware=[MCPPolicy()])
    from app.knowledge_skill_tools import register_knowledge_skill_tools
    register_knowledge_skill_tools(server)
    register_memory_tools(server, selector=native.pack_context, backend='mojo')

    @server.tool(annotations=tool_annotations('search_knowledge_base'))
    def search_knowledge_base(query: str, limit: int = 3) -> str:
        """Search indexed documents with the Mojo retrieval handler."""
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        return str(native.search_knowledge_base(query, limit))

    @server.tool(annotations=tool_annotations('create_support_ticket'))
    def create_support_ticket(ticket_id: str, email: str, summary: str) -> str:
        """Create a support record using the Mojo handler."""
        return str(native.create_support_ticket(ticket_id, email, summary))

    @server.tool(annotations=tool_annotations('get_ticket'))
    def get_ticket(ticket_id: str) -> str:
        """Read a support record using the Mojo handler."""
        return str(native.get_support_ticket(ticket_id))

    @server.tool(annotations=tool_annotations('update_ticket_status'))
    def update_ticket_status(ticket_id: str, status: str) -> str:
        """Update a support record using the Mojo handler."""
        return str(native.update_ticket_status(ticket_id, status))

    @server.tool(annotations=tool_annotations('list_tickets'))
    def list_tickets(status: str = "") -> str:
        """List support records using the Mojo handler."""
        return str(native.list_support_tickets(status))

    @server.tool(annotations=tool_annotations('search_tools'))
    def search_tools(query: str, category: str = "", limit: int = 3) -> str:
        """Discover tool descriptions in the shared Python registry."""
        from app.tool_rag import format_tool_search_results
        return format_tool_search_results(query=query, category=category, limit=limit)

    @server.tool(annotations=tool_annotations('distill_trajectory_to_skill'))
    def distill_trajectory_to_skill(session_id: str, skill_name: str, description: str = "") -> str:
        """Draft an inactive candidate skill through the shared Python trajectory recorder."""
        from app.trajectory_recorder import distill_trajectory_to_skill as distill
        return distill(session_id=session_id, skill_name=skill_name, description=description)

    def read_skill() -> str:
        return markdown_path(SKILLS_DIR, "customer_service").read_text(encoding="utf-8")

    @server.resource("skills://customer_service")
    def customer_service_resource() -> str:
        """Read the customer service playbook."""
        return read_skill()

    @server.prompt()
    def customer_service_sop() -> str:
        """Load the customer service playbook."""
        return read_skill()

    return server
