"""AnyTool-Inspired Smart Tool RAG, Schema Catalog, and Self-Healing Analytics.

Optimized for local LLMs:
- Dynamically retrieves top-K relevant tool schemas on-demand instead of bloating system prompt
- Tracks execution latency, success/failure counts, and error rates per tool in SQLite
- Provides self-healing error analysis and automatic fallback recommendations
"""

import heapq
import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from app.db import get_connection

# In-memory registry of tool definitions
_REGISTERED_TOOLS: Dict[str, Dict[str, Any]] = {}
_CATALOG_CACHE: Dict[str, List[Dict[str, Any]]] = {}
_TOOL_SEARCH_CACHE: Dict[str, List[Dict[str, Any]]] = {}
_TOOL_SEARCH_CACHE_MAX = 512


def clear_tool_cache() -> None:
    """Invalidates in-memory tool catalog and search cache upon tool updates."""
    _CATALOG_CACHE.clear()
    _TOOL_SEARCH_CACHE.clear()
    from app.tool_embeddings import clear_results
    clear_results()


def register_tool(
    name: str,
    description: str,
    category: str = "general",
    parameters: Optional[Dict[str, Any]] = None,
    examples: Optional[List[str]] = None,
    db_path: Path | str | None = None,
) -> None:
    """Registers a tool in memory and synchronizes with SQLite tool_registry."""
    parameters = parameters or {}
    examples = examples or []
    tool_data = {
        "tool_name": name,
        "category": category,
        "description": description,
        "parameters": parameters,
        "examples": examples,
    }
    _REGISTERED_TOOLS[name] = tool_data
    clear_tool_cache()

    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT OR REPLACE INTO tool_registry (tool_name, category, description, parameters_json)
        VALUES (?, ?, ?, ?)
        """,
        (name, category, description, json.dumps({"parameters": parameters, "examples": examples})),
    )
    conn.commit()


def record_tool_call(
    tool_name: str,
    success: bool,
    latency_ms: float,
    error: str = "",
    db_path: Path | str | None = None,
) -> None:
    """Records an execution attempt into tool_stats for reliability scoring and health monitoring."""
    clear_tool_cache()
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO tool_stats (
            tool_name, call_count, success_count, fail_count, total_latency_ms, last_latency_ms, last_error, last_called
        ) VALUES (?, 1, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(tool_name) DO UPDATE SET
            call_count = call_count + 1,
            success_count = success_count + ?,
            fail_count = fail_count + ?,
            total_latency_ms = total_latency_ms + ?,
            last_latency_ms = ?,
            last_error = ?,
            last_called = CURRENT_TIMESTAMP
        """,
        (
            tool_name,
            1 if success else 0,
            0 if success else 1,
            latency_ms,
            latency_ms,
            error,
            1 if success else 0,
            0 if success else 1,
            latency_ms,
            latency_ms,
            error,
        ),
    )
    conn.commit()


def search_tools(
    query: str,
    category: str = "",
    limit: int = 3,
    db_path: Path | str | None = None,
    *, semantic: bool = True,
) -> List[Dict[str, Any]]:
    """Discover tools with local EmbeddingGemma 2; semantic=False is explicit lexical-only lookup."""
    if semantic:
        from app.tool_embeddings import search
        return search(query, category, limit, db_path)
    db_key = str(db_path) if db_path is not None else "default"
    clean_q = query.strip().lower()
    clean_cat = category.strip().lower()
    cache_key = f"{db_key}::{clean_q}::{clean_cat}::{limit}"
    if cache_key in _TOOL_SEARCH_CACHE:
        return _TOOL_SEARCH_CACHE[cache_key]

    if db_key not in _CATALOG_CACHE:
        conn = get_connection(db_path)
        cur = conn.cursor()
        cur.execute("""
        SELECT r.tool_name, r.category, r.description, r.parameters_json,
               COALESCE(s.call_count, 0), COALESCE(s.success_count, 0),
               COALESCE(s.last_latency_ms, 0.0), COALESCE(s.last_error, '')
        FROM tool_registry r
        LEFT JOIN tool_stats s ON r.tool_name = s.tool_name
        WHERE r.is_active = 1
        """)
        rows = cur.fetchall()

        catalog = []
        for row in rows:
            t_name, t_cat, t_desc, t_params_json, calls, successes, lat_ms, l_err = row
            params_data = json.loads(t_params_json) if t_params_json else {}
            catalog.append({
                "tool_name": t_name,
                "category": t_cat,
                "description": t_desc,
                "parameters": params_data.get("parameters", {}),
                "examples": params_data.get("examples", []),
                "call_count": calls,
                "success_count": successes,
                "last_latency_ms": lat_ms,
                "last_error": l_err,
                "searchable_text": f"{t_name} {t_cat} {t_desc}".lower(),
            })
        _CATALOG_CACHE[db_key] = catalog

    catalog = _CATALOG_CACHE[db_key]
    query_tokens = set(clean_q.replace("_", " ").split())
    scored_tools = []

    for item in catalog:
        if clean_cat and item["category"].lower() != clean_cat:
            continue

        searchable_text = item["searchable_text"]
        matches = sum(map(searchable_text.__contains__, query_tokens))
        if matches == 0 and query_tokens:
            continue

        calls = item["call_count"]
        successes = item["success_count"]
        reliability = (successes / calls) if calls > 0 else 1.0
        score = (matches * 10.0) + (reliability * 2.0)

        scored_tools.append((score, item, reliability))

    if 0 < limit < len(scored_tools):
        top_tools = heapq.nlargest(limit, scored_tools, key=lambda candidate: candidate[0])
    else:
        top_tools = sorted(scored_tools, key=lambda candidate: candidate[0], reverse=True)[:limit]
    result = [
        {
            "tool_name": item["tool_name"],
            "category": item["category"],
            "description": item["description"],
            "parameters": item["parameters"],
            "examples": item["examples"],
            "score": score,
            "call_count": item["call_count"],
            "reliability_pct": round(reliability * 100, 1),
            "last_latency_ms": round(item["last_latency_ms"], 2),
        }
        for score, item, reliability in top_tools
    ]
    _TOOL_SEARCH_CACHE[cache_key] = result
    if len(_TOOL_SEARCH_CACHE) > _TOOL_SEARCH_CACHE_MAX:
        _TOOL_SEARCH_CACHE.pop(next(iter(_TOOL_SEARCH_CACHE)))
    return result


def format_tool_search_results(
    query: str,
    category: str = "",
    limit: int = 3,
    db_path: Path | str | None = None,
) -> str:
    """Formats top-matching tool schemas specifically formatted for local LLM prompt injection."""
    matches = search_tools(query, category=category, limit=limit, db_path=db_path)
    if not matches:
        return f"No tools matching query '{query}' were found. Check category or query keywords."

    lines = [f"Found {len(matches)} matching tool(s) for query '{query}':\n"]
    for t in matches:
        lines.append(f"### Tool: `{t['tool_name']}` ({t['category']})")
        lines.append(f"**Description**: {t['description']}")
        reliability = f"{t['reliability_pct']}%" if t['reliability_pct'] is not None else 'Not measured'
        lines.append(f"**Reliability**: {reliability} ({t['call_count']} calls)")
        if t["parameters"]:
            lines.append("**Parameters**:")
            for p_name, p_info in t["parameters"].items():
                p_type = p_info.get("type", "string")
                p_desc = p_info.get("description", "")
                p_req = " (Required)" if p_info.get("required", False) else " (Optional)"
                lines.append(f"  - `{p_name}` [{p_type}]{p_req}: {p_desc}")
        if t["examples"]:
            lines.append(f"**Example**: `{t['examples'][0]}`")
        lines.append("")

    return "\n".join(lines).strip()


def get_tool_health_report(db_path: Path | str | None = None) -> str:
    """Generates an operational health report for all executed tools."""
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("""
    SELECT r.tool_name, r.category,
           COALESCE(s.call_count, 0) as calls,
           COALESCE(s.success_count, 0) as successes,
           COALESCE(s.fail_count, 0) as fails,
           COALESCE(s.total_latency_ms, 0.0) as total_ms,
           COALESCE(s.last_latency_ms, 0.0) as last_ms,
           COALESCE(s.last_error, '') as err,
           COALESCE(s.last_called, 'Never') as last_ts
    FROM tool_registry r
    LEFT JOIN tool_stats s ON r.tool_name = s.tool_name
    ORDER BY calls DESC, r.tool_name ASC
    """)
    rows = cur.fetchall()

    if not rows:
        return "No tools recorded in registry."

    lines = [
        "| Tool Name | Category | Calls | Success % | Avg Latency | Last Error |",
        "|-----------|----------|-------|-----------|-------------|------------|",
    ]
    for row in rows:
        name, cat, calls, succ, fail, total_ms, last_ms, err, ts = row
        rate = f"{round((succ / calls) * 100, 1)}%" if calls > 0 else "N/A"
        avg_lat = f"{round(total_ms / calls, 2)}ms" if calls > 0 else "N/A"
        err_short = (err[:25] + "...") if len(err) > 25 else (err or "None")
        lines.append(f"| `{name}` | {cat} | {calls} | {rate} | {avg_lat} | {err_short} |")

    return "\n".join(lines)


def handle_tool_failure(
    tool_name: str,
    error_message: str,
    attempted_args: Optional[Dict[str, Any]] = None,
    db_path: Path | str | None = None,
) -> str:
    """Self-healing recovery advice and alternative tool recommendations when a tool execution fails."""
    # Find alternatives in the same category or with overlapping functionality
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT category FROM tool_registry WHERE tool_name = ?", (tool_name,))
    cat_row = cur.fetchone()
    category = cat_row[0] if cat_row else "general"

    alternatives = search_tools(query=category, category=category, limit=3, db_path=db_path)
    alt_names = [a["tool_name"] for a in alternatives if a["tool_name"] != tool_name]

    lines = [
        f"❌ Tool `{tool_name}` failed with error: {error_message}",
        "\n**Self-Healing Guidance for Local LLM**:",
        "1. Verify argument types and required parameters.",
    ]
    if attempted_args:
        lines.append(f"   Provided args: `{json.dumps(attempted_args)}`")
    if alt_names:
        lines.append(f"2. Consider fallback alternatives: {', '.join(f'`{a}`' for a in alt_names)}")
    lines.append("3. If problem persists, inspect system metrics via `get_system_metrics`.")

    return "\n".join(lines)


def init_default_tool_registry(db_path: Path | str | None = None) -> None:
    """Pre-populates the tool registry with ROMS built-in tools for Smart Tool RAG."""
    default_tools = [
        {
            "name": "search_knowledge_base",
            "category": "rag",
            "description": "Semantic hybrid search across all ingested OKF documents, CSV tables, and code.",
            "parameters": {
                "query": {"type": "string", "description": "Search query or natural language question", "required": True},
                "limit": {"type": "integer", "description": "Max chunks to retrieve (default 3)", "required": False},
            },
            "examples": ["search_knowledge_base(query='damaged in transit replacement window', limit=3)"],
        },
        {
            "name": "search_grounded_context",
            "category": "rag",
            "description": "Retrieves high-precision knowledge context formatted in clean XML tags for local LLMs.",
            "parameters": {
                "query": {"type": "string", "description": "Information topic to ground", "required": True},
                "limit": {"type": "integer", "description": "Number of sources", "required": False},
                "max_tokens": {"type": "integer", "description": "Max token budget for context", "required": False},
            },
            "examples": ["search_grounded_context(query='return policy hardware failure')"],
        },
        {
            "name": "create_support_ticket",
            "category": "operational",
            "description": "Inserts a verified customer support ticket into the operational SQLite database.",
            "parameters": {
                "ticket_id": {"type": "string", "description": "Unique identifier (e.g. TICK-1024)", "required": True},
                "email": {"type": "string", "description": "Customer registered email", "required": True},
                "summary": {"type": "string", "description": "Clear description of the customer issue", "required": True},
            },
            "examples": ["create_support_ticket(ticket_id='TICK-500', email='user@corp.com', summary='Screen cracked')"],
        },
        {
            "name": "get_ticket",
            "category": "operational",
            "description": "Retrieves operational details and current status of a specific support ticket.",
            "parameters": {
                "ticket_id": {"type": "string", "description": "Ticket ID to query", "required": True},
            },
            "examples": ["get_ticket(ticket_id='TICK-500')"],
        },
        {
            "name": "update_ticket_status",
            "category": "operational",
            "description": "Updates ticket status (e.g. OPEN, URGENT, RESOLVED, CLOSED).",
            "parameters": {
                "ticket_id": {"type": "string", "description": "Target ticket ID", "required": True},
                "status": {"type": "string", "description": "New status code", "required": True},
            },
            "examples": ["update_ticket_status(ticket_id='TICK-500', status='URGENT')"],
        },
        {
            "name": "list_tickets",
            "category": "operational",
            "description": "Lists recent support tickets, optionally filtered by status.",
            "parameters": {
                "status": {"type": "string", "description": "Optional filter like OPEN or URGENT", "required": False},
            },
            "examples": ["list_tickets(status='OPEN')"],
        },
        {
            "name": "list_skills",
            "category": "skills",
            "description": "Lists all available agent procedural SOP playbooks in the skills directory.",
            "parameters": {},
            "examples": ["list_skills()"],
        },
        {
            "name": "add_skill",
            "category": "skills",
            "description": "Creates or updates an SOP playbook in the skills directory.",
            "parameters": {
                "skill_name": {"type": "string", "description": "Unique skill identifier", "required": True},
                "content": {"type": "string", "description": "Markdown SOP contents", "required": True},
            },
            "examples": ["add_skill(skill_name='db_backup', content='# Backup SOP...')"],
        },
        {
            "name": "search_tools",
            "category": "meta",
            "description": "Discovers and returns exact schemas for relevant tools matching an agent's task.",
            "parameters": {
                "query": {"type": "string", "description": "Description of action needed", "required": True},
                "category": {"type": "string", "description": "Optional category (rag, operational, skills, sandboxed)", "required": False},
                "limit": {"type": "integer", "description": "Max tools to return", "required": False},
            },
            "examples": ["search_tools(query='create customer ticket')"],
        },
        {
            "name": "get_system_metrics",
            "category": "system",
            "description": "Returns host CPU %, RAM availability, and ROMS indexed counts.",
            "parameters": {},
            "examples": ["get_system_metrics()"],
        },
        {
            "name": "run_sandboxed_command",
            "category": "sandboxed",
            "description": "Executes a command inside an isolated Podman/Docker container with hardware resource limits.",
            "parameters": {
                "image": {"type": "string", "description": "Container image", "required": True},
                "command": {"type": "string", "description": "Command to run", "required": True},
            },
            "examples": ["run_sandboxed_command(image='alpine:latest', command='ls -la')"],
        },
        {
            "name": "distill_trajectory_to_skill",
            "category": "skills",
            "description": "UpSkill engine: synthesizes a recorded agent task execution trajectory into a permanent skills SOP.",
            "parameters": {
                "session_id": {"type": "string", "description": "Completed session ID", "required": True},
                "skill_name": {"type": "string", "description": "Name for the new skill SOP", "required": True},
                "description": {"type": "string", "description": "Summary of the skill", "required": False},
            },
            "examples": ["distill_trajectory_to_skill(session_id='sess_123', skill_name='customer_refund')"],
        },
    ]

    for tool in default_tools:
        register_tool(
            name=tool["name"],
            category=tool["category"],
            description=tool["description"],
            parameters=tool["parameters"],
            examples=tool["examples"],
            db_path=db_path,
        )
