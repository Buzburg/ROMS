"""
Standards-Compliant Model Context Protocol (MCP) JSON-RPC 2.0 Server for mojo-cortex.
Plugs directly into Claude Code, Cursor, Windsurf, Cline, Goose, and Claude Desktop over stdio.
"""

import sys
import json
from .memory import HybridNeuralMemory
from .sieve import ContextSieve
from .symdex import PolyglotSymdex
from .rewind import WorkspaceTimeMachine
from .shield import ExecutionShield

MCP_TOOLS_SCHEMA = [
    {
        "name": "cortex_memory_remember",
        "description": "Store or cleanly overwrite a persistent architectural fact or project rule using Titans + DeltaNet-2 neural memory.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Concept or variable identifier"},
                "value": {"type": "string", "description": "Fact or value to memorize"},
                "category": {"type": "string", "default": "architecture"}
            },
            "required": ["key", "value"]
        }
    },
    {
        "name": "cortex_memory_recall",
        "description": "Recall a persistent fact or project rule from associative neural memory in <100 microseconds.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Key or semantic concept to recall"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "cortex_memory_erase",
        "description": "Surgically erase an obsolete key from neural memory using the Gated DeltaNet-2 pure erase gate.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Key to erase"}
            },
            "required": ["key"]
        }
    },
    {
        "name": "cortex_symdex_lookup",
        "description": "Locate function, class, struct, or interface definitions across the codebase in <150 microseconds without reading full files.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Symbol name to find"},
                "top_k": {"type": "integer", "default": 5}
            },
            "required": ["query"]
        }
    },
    {
        "name": "cortex_sieve_compact",
        "description": "Compact verbose terminal logs or test outputs by 90-98% using SnapKV observation windows while retaining all stack traces and errors.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "raw_text": {"type": "string", "description": "Raw terminal or build output"},
                "max_lines": {"type": "integer", "default": 30}
            },
            "required": ["raw_text"]
        }
    },
    {
        "name": "cortex_snapshot_create",
        "description": "Create a deduplicated copy-on-write workspace snapshot before executing risky multi-file edits.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "label": {"type": "string", "default": "Agent pre-edit checkpoint"}
            }
        }
    },
    {
        "name": "cortex_snapshot_rewind",
        "description": "Atomically rewind the workspace to a previous snapshot without altering .git history.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "snapshot_id": {"type": "string", "description": "Snapshot ID (e.g. snap_001)"}
            },
            "required": ["snapshot_id"]
        }
    },
    {
        "name": "cortex_shield_forecast",
        "description": "Evaluate a candidate shell command or action for goal alignment, cyclic loops, and destructive hazards before execution.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "Proposed command or action"},
                "goal": {"type": "string", "description": "Active task objective"}
            },
            "required": ["action"]
        }
    }
]


class CortexMCPServer:
    def __init__(self, cortex_dir: str = ".cortex", workspace_root: str = "."):
        self.workspace_root = workspace_root
        self.memory = HybridNeuralMemory(cortex_dir)
        self.sieve = ContextSieve(cortex_dir)
        self.symdex = PolyglotSymdex(cortex_dir)
        self.rewind = WorkspaceTimeMachine(cortex_dir)
        self.shield = ExecutionShield(cortex_dir)

    def handle_request(self, request: dict) -> dict:
        req_id = request.get("id")
        method = request.get("method", "")
        params = request.get("params", {}) or {}

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {"name": "mojo-cortex", "version": "1.0.0"},
                    "capabilities": {"tools": {}}
                }
            }

        elif method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": MCP_TOOLS_SCHEMA}
            }

        elif method == "tools/call":
            tool_name = params.get("name")
            args = params.get("arguments", {}) or {}
            try:
                result_payload = self._dispatch_tool(tool_name, args)
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(result_payload, indent=2)}],
                        "isError": False
                    }
                }
            except Exception as e:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": f"Error: {e}"}],
                        "isError": True
                    }
                }

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method '{method}' not found"}
        }

    def _dispatch_tool(self, name: str, args: dict) -> dict:
        if name == "cortex_memory_remember":
            return self.memory.remember(
                args["key"], args["value"], category=args.get("category", "architecture")
            )
        elif name == "cortex_memory_recall":
            return self.memory.recall(args["query"])
        elif name == "cortex_memory_erase":
            return self.memory.erase(args["key"])
        elif name == "cortex_symdex_lookup":
            return self.symdex.lookup(args["query"], top_k=int(args.get("top_k", 5)))
        elif name == "cortex_sieve_compact":
            return self.sieve.compact(args["raw_text"], max_lines=int(args.get("max_lines", 30)))
        elif name == "cortex_snapshot_create":
            return self.rewind.snapshot(args.get("label", "MCP pre-edit checkpoint"), self.workspace_root)
        elif name == "cortex_snapshot_rewind":
            return self.rewind.rewind(args["snapshot_id"], self.workspace_root)
        elif name == "cortex_shield_forecast":
            return self.shield.forecast_action(args["action"], goal=args.get("goal"))
        else:
            raise ValueError(f"Unknown MCP tool: {name}")

    def serve_stdio(self):
        """Runs the JSON-RPC 2.0 stdio loop for Claude Code / Cursor / Windsurf."""
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
                # Ignore notifications without an id
                if "id" not in req:
                    continue
                resp = self.handle_request(req)
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()
            except Exception as e:
                err_resp = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {e}"}
                }
                sys.stdout.write(json.dumps(err_resp) + "\n")
                sys.stdout.flush()
