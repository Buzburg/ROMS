"""Compact Small-Model Scaffold for RWKV-7 & Goose.

Tuned specifically for sub-10B local models running on CPU (such as Omarchy's RWKV-7 2.9B),
incorporating the core findings from itayinbarr/little-coder and 1jehuang/jcode:
1. Strict sub-1,000 token system prompt (preventing cognitive collapse).
2. Minimal 4-tool primitive surface (read_file, write_file, edit_file, run_sandbox_command).
3. Immutable temporal anchor (strict 2026 anchor, matching Omarchy Mojo.pdf Page 21).
4. Deterministic structured JSON tool calling schema.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional


CORE_PRIMITIVE_TOOLS = [
    {
        "name": "read_file",
        "description": "Read file lines with bounded offset and limit.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path to file"},
                "offset": {"type": "integer", "description": "Starting line number (1-based)"},
                "limit": {"type": "integer", "description": "Maximum number of lines to read"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "write_file",
        "description": "Write entire content to target path in workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path to file"},
                "content": {"type": "string", "description": "Raw file content to write"}
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "edit_file",
        "description": "Exact substring replacement in target file.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path to file"},
                "old_str": {"type": "string", "description": "Exact text chunk to replace"},
                "new_str": {"type": "string", "description": "New replacement text"}
            },
            "required": ["path", "old_str", "new_str"]
        }
    },
    {
        "name": "run_sandbox_command",
        "description": "Run registered command inside Landlock/Podman worker sandbox.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Command to run (e.g. pytest tests)"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (max 60)"}
            },
            "required": ["command"]
        }
    }
]


def build_compact_system_prompt(
    persona_name: str = "ROMS",
    project_id: str = "omarchy",
    custom_instructions: str = "",
    include_temporal_anchor: bool = True
) -> str:
    """Generates an ultra-compact (<1,000 tokens) prompt engineered for RWKV-7 CPU."""
    now_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    parts = []
    
    if include_temporal_anchor:
        parts.append(
            f"[SYSTEM_ANCHOR]\n"
            f"Current Date: {now_date}\n"
            f"Epoch Year: 2026\n"
            f"Operating System: Omarchy OS (Arch Linux Base)\n"
            f"Enforcement: Native Mojo Landlock Broker + Podman Worker Sandbox\n"
            f"Rule: Deterministic validation gates sit outside the model.\n"
        )
        
    parts.append(
        f"You are {persona_name}, the local ROMS assistant.\n"
        f"You are running locally. Be concise, direct, and exact.\n"
        f"When modifying code, generate minimal, safe diffs or call tools precisely.\n"
        f"Never hallucinate external package managers or bypass sandbox boundaries.\n"
    )
    
    if custom_instructions:
        parts.append(f"Project Directives ({project_id}):\n{custom_instructions.strip()}\n")
        
    parts.append(
        "Available Tools:\n"
        "- read_file(path, offset, limit)\n"
        "- write_file(path, content)\n"
        "- edit_file(path, old_str, new_str)\n"
        "- run_sandbox_command(command, timeout)\n\n"
        "To invoke a tool, output a single JSON block:\n"
        "```json\n"
        '{"tool": "read_file", "arguments": {"path": "src/main.py", "offset": 1, "limit": 50}}\n'
        "```"
    )
    
    return "\n".join(parts)


def parse_tool_invocation(text: str) -> Optional[Dict[str, Any]]:
    """Strictly parses JSON tool invocations emitted by small models without fuzz."""
    text = text.strip()
    if "```json" in text:
        try:
            block = text.split("```json")[1].split("```")[0].strip()
            data = json.loads(block)
            if isinstance(data, dict) and "tool" in data and "arguments" in data:
                return data
        except Exception:
            pass
    elif text.startswith("{") and text.endswith("}"):
        try:
            data = json.loads(text)
            if isinstance(data, dict) and "tool" in data and "arguments" in data:
                return data
        except Exception:
            pass
    return None
