"""Example Custom Tool Plugin for ROMS.

To add new MCP tools to ROMS, simply create a python file in custom_tools/
and define a register_tools(mcp) function. Enable it explicitly with
ROMS_MCP_PROFILE=local and ROMS_MCP_PLUGINS=example_tool.
"""

from app.mcp_annotations import tool_annotations

def register_tools(mcp):
    """Registers custom tools directly into the ROMS FastMCP engine."""

    @mcp.tool(annotations=tool_annotations('calculate_refund_amount'))
    def calculate_refund_amount(item_price: float, return_shipping_fee: float = 0.0) -> str:
        """Calculate an amount only; never issues a refund or contacts a payment service."""
        total = max(0.0, item_price - return_shipping_fee)
        return f"Final refundable amount: ${total:.2f} (Original: ${item_price:.2f}, Shipping Fee: ${return_shipping_fee:.2f})"
