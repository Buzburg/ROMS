"""Operator-configured MCP policy and capability hints; hints are not authorization."""
from collections import deque
import os
import threading
import time

from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware

from app.mcp_annotations import READ_TOOLS, DESTRUCTIVE_TOOLS, tool_annotations, plugin_allowed


class MCPPolicy(Middleware):
    """Bound calls per server process and enforce operator-selected capabilities."""
    def __init__(self, *, profile=None, allow_destructive=None, calls_per_minute=None, max_concurrent=None, clock=time.monotonic):
        self.profile = profile or os.getenv('ROMS_MCP_PROFILE', 'read_only')
        if self.profile not in {'read_only', 'local'}:
            raise ValueError('ROMS_MCP_PROFILE must be read_only or local')
        self.allow_destructive = (os.getenv('ROMS_MCP_ALLOW_DESTRUCTIVE') == '1'
                                  if allow_destructive is None else allow_destructive)
        self.limit = int(os.getenv('ROMS_MCP_CALLS_PER_MINUTE', '60') if calls_per_minute is None else calls_per_minute)
        self.concurrent = int(os.getenv('ROMS_MCP_MAX_CONCURRENT', '4') if max_concurrent is None else max_concurrent)
        if not 1 <= self.limit <= 600 or not 1 <= self.concurrent <= 16:
            raise ValueError('MCP limits must be 1–600 calls/minute and 1–16 concurrent calls')
        self.clock, self.calls, self.inflight = clock, deque(), 0
        self.lock = threading.Lock()

    async def on_call_tool(self, context, call_next):
        name = context.message.name
        with self.lock:
            now = self.clock()
            while self.calls and self.calls[0] <= now - 60:
                self.calls.popleft()
            if len(self.calls) >= self.limit:
                raise ToolError('MCP rate limit reached; wait before retrying.')
            self.calls.append(now)  # Denied attempts also consume the request budget.
            if self.profile == 'read_only' and name not in READ_TOOLS:
                raise ToolError('Tool disabled by read_only MCP profile. The operator can select ROMS_MCP_PROFILE=local before starting the server.')
            if name in DESTRUCTIVE_TOOLS and not self.allow_destructive:
                raise ToolError('Destructive MCP tools are disabled. The operator must explicitly enable ROMS_MCP_ALLOW_DESTRUCTIVE=1.')
            if self.inflight >= self.concurrent:
                raise ToolError('MCP concurrent-call limit reached; wait for a running call.')
            self.inflight += 1
        try:
            return await call_next(context)
        finally:
            with self.lock:
                self.inflight -= 1
