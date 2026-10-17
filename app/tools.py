"""ROMS Business Actions and Sandboxed Task Execution Tools."""

import json
import frontmatter
import os
from pathlib import Path
from app.safe_paths import markdown_path
from typing import Any, Dict, List, Optional

from app.config import (
    BASE_REPOS_DIR,
    WORKSPACES_DIR,
    KNOWLEDGE_DIR,
    SKILLS_DIR,
    TOOL_EXECUTION_TIMEOUT,
)
from app.db import get_connection
from app.throttle import tool_limiter
from app.okf_loader import ingest_okf_file, ingest_okf_directory


# ==========================================
# Operational Database Tools (Support Tickets)
# ==========================================


def create_support_ticket(
    ticket_id: str,
    customer_email: str,
    issue_summary: str,
    db_path: Path | str | None = None,
) -> str:
    """Inserts a verified customer support ticket into the operational database."""
    conn = get_connection(db_path)
    cur = conn.cursor()
    try:
        cur.execute(
            """
        INSERT INTO support_tickets (ticket_id, customer_email, issue_summary)
        VALUES (?, ?, ?)
        """,
            (ticket_id, customer_email, issue_summary),
        )
        conn.commit()
        return f"Ticket {ticket_id} created successfully."
    except Exception as e:
        return f"Error creating ticket: {str(e)}"
    finally:
        conn.close()


def get_support_ticket(
    ticket_id: str, db_path: Path | str | None = None
) -> Optional[Dict[str, Any]]:
    """Retrieves ticket details by ticket ID."""
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        """
    SELECT ticket_id, customer_email, issue_summary, status, created_at
    FROM support_tickets
    WHERE ticket_id = ?
    """,
        (ticket_id,),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "ticket_id": row[0],
        "customer_email": row[1],
        "issue_summary": row[2],
        "status": row[3],
        "created_at": str(row[4]),
    }


def update_ticket_status(
    ticket_id: str, status: str, db_path: Path | str | None = None
) -> str:
    """Updates the status of an existing ticket (e.g. OPEN, URGENT, RESOLVED, CLOSED)."""
    conn = get_connection(db_path)
    cur = conn.cursor()
    try:
        cur.execute(
            """
        UPDATE support_tickets
        SET status = ?
        WHERE ticket_id = ?
        """,
            (status, ticket_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            return f"Ticket {ticket_id} not found."
        return f"Ticket {ticket_id} status updated to '{status}'."
    except Exception as e:
        return f"Error updating ticket: {str(e)}"
    finally:
        conn.close()


def list_support_tickets(
    status: Optional[str] = None, db_path: Path | str | None = None
) -> List[Dict[str, Any]]:
    """Lists support tickets, optionally filtered by status."""
    conn = get_connection(db_path)
    cur = conn.cursor()
    if status:
        cur.execute(
            """
        SELECT ticket_id, customer_email, issue_summary, status, created_at
        FROM support_tickets
        WHERE status = ?
        ORDER BY created_at DESC
        """,
            (status,),
        )
    else:
        cur.execute("""
        SELECT ticket_id, customer_email, issue_summary, status, created_at
        FROM support_tickets
        ORDER BY created_at DESC
        """)
    rows = cur.fetchall()
    conn.close()
    return [
        {
            "ticket_id": r[0],
            "customer_email": r[1],
            "issue_summary": r[2],
            "status": r[3],
            "created_at": str(r[4]),
        }
        for r in rows
    ]


# ==========================================
# Dynamic Knowledge & Skills Management Tools
# ==========================================


def list_skills() -> List[str]:
    """Lists all available agent skill SOP files in the skills directory."""
    if not SKILLS_DIR.exists():
        return []
    return [f.stem for f in SKILLS_DIR.glob("*.md")]


def add_skill(skill_name: str, content: str) -> str:
    """Creates or updates a skill SOP markdown file in the skills directory."""
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    clean_name = skill_name.replace(".md", "").strip().lower()
    skill_file = markdown_path(SKILLS_DIR, clean_name)
    skill_file.write_text(content, encoding="utf-8")
    return f"Skill '{clean_name}' saved to {skill_file.name}. Immediately accessible as skills://{clean_name}"


def list_knowledge_documents(db_path: Path | str | None = None) -> List[Dict[str, Any]]:
    """Lists all indexed knowledge documents from okf_registry."""
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT doc_id, title, doc_type, checksum, last_indexed FROM okf_registry ORDER BY doc_id ASC")
    rows = cur.fetchall()
    conn.close()
    return [
        {
            "doc_id": r[0],
            "title": r[1],
            "doc_type": r[2],
            "checksum": r[3],
            "last_indexed": str(r[4]),
        }
        for r in rows
    ]


def add_knowledge_document(
    filename: str,
    content: str,
    title: str = "",
    doc_type: str = "general",
    db_path: Path | str | None = None,
) -> str:
    """Adds a new OKF Markdown document to knowledge/ and indexes it in the vector DB."""
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    if not filename.endswith(".md"):
        filename = f"{filename}.md"

    doc_path = markdown_path(KNOWLEDGE_DIR, filename)
    doc_title = title if title else filename

    file_text = frontmatter.dumps(frontmatter.Post(
        content.strip(), okf_version="0.2", type=doc_type, title=doc_title
    ))
    doc_path.write_text(file_text, encoding="utf-8")

    ingested = ingest_okf_file(doc_path, db_path=db_path)
    status_str = "indexed into vector store" if ingested else "already up to date"
    return f"Document '{filename}' saved and {status_str}."


def reload_knowledge(db_path: Path | str | None = None) -> str:
    """Re-scans the knowledge directory and updates vector embeddings for new/modified files."""
    count = ingest_okf_directory(KNOWLEDGE_DIR, db_path=db_path)
    from app.okf_loader import get_ingestion_status
    status = get_ingestion_status(db_path)
    return f"Knowledge reload complete: {count} new or updated document(s) indexed. " + json.dumps(status, ensure_ascii=False)


# ==========================================
# Output Sanitization & Truncation
# ==========================================


def sanitize_output(output: str, max_length: int = 2500) -> str:
    """Hard response truncation to prevent exploding LLM context windows."""
    if len(output) > max_length:
        head_len = (max_length - 50) // 2
        tail_len = head_len
        return (
            output[:head_len]
            + "\n...[OUTPUT TRUNCATED BY MCP GUARDIAN]...\n"
            + output[-tail_len:]
        )
    return output


# ==========================================
# Sandboxed Task Execution
# ==========================================


from app.worker_tools import run_sandboxed_command, execute_tool_task


def get_system_metrics(db_path: Path | str | None = None) -> Dict[str, Any]:
    """Returns real-time host hardware metrics and ROMS database statistics."""
    import psutil

    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("""
    SELECT
        (SELECT count(*) FROM okf_registry),
        (SELECT count(*) FROM vec_chunks),
        (SELECT count(*) FROM embedding_cache),
        (SELECT count(*) FROM support_tickets WHERE status = 'OPEN')
    """)
    doc_count, chunk_count, cache_count, open_tickets = cur.fetchone()
    conn.close()

    mem = psutil.virtual_memory()
    return {
        "host_cpu_percent": psutil.cpu_percent(interval=None),
        "available_ram_mb": round(mem.available / (1024 * 1024), 1),
        "total_ram_mb": round(mem.total / (1024 * 1024), 1),
        "ingested_documents": doc_count,
        "indexed_chunks": chunk_count,
        "cached_query_embeddings": cache_count,
        "registered_skills": len(list_skills()),
        "open_tickets": open_tickets,
    }


# ==========================================
# [M] Smart Tool RAG & Self-Healing (AnyTool)
# ==========================================

from app.tool_rag import (
    search_tools,
    format_tool_search_results,
    get_tool_health_report,
    record_tool_call,
    register_tool,
    init_default_tool_registry,
    handle_tool_failure,
)


def search_tools_catalog(query: str, category: str = "", limit: int = 3, db_path: Path | str | None = None) -> str:
    """Discovers and formats matching tool schemas on-demand for local LLMs."""
    return format_tool_search_results(query=query, category=category, limit=limit, db_path=db_path)


def get_tool_health(db_path: Path | str | None = None) -> str:
    """Generates an operational health and latency report for all registered tools."""
    return get_tool_health_report(db_path=db_path)


# ==========================================
# [S] UpSkill Trajectory Distillation
# ==========================================

from app.trajectory_recorder import (
    start_session as start_trajectory_session,
    record_step as record_trajectory_step,
    finish_session as finish_trajectory_session,
    distill_trajectory_to_skill,
    get_trajectory,
)


# ==========================================
# [R] ZG-Search (Zero-Gravity Fuzzy & Faceted)
# ==========================================

from app.zgsearch import zg_search as _zg_search, get_zg_facets as _get_zg_facets


def zg_search_engine(query: str, doc_type: str = "", limit: int = 5,
                     db_path: Path | str | None = None, *, topic: str = "", doc_id: str = "") -> str:
    """Compatibility formatter for the one local search engine."""
    filters = {key: value for key, value in
               (("doc_type", doc_type), ("topic", topic), ("doc_id", doc_id)) if value}
    results = _zg_search(query=query, filters=filters, limit=limit, db_path=db_path)
    if not results:
        return f"No results found for query '{query}'."
    lines = [f"Local search results for '{query}':"]
    for idx, result in enumerate(results, 1):
        lines.append(f"[{idx}] {result['title']} ({result['doc_type']}) - Score: {result['score']:.4f}")
        lines.append(f"    Source: {result.get('source_path') or result['doc_id']} | doc_id={result['doc_id']} | chunk_id={result['chunk_id']}")
        lines.append(result['content'][:250])
    return "\n".join(lines)


def get_zg_search_facets(db_path: Path | str | None = None) -> Dict[str, Any]:
    """Returns faceted document distribution across types and total chunks."""
    return _get_zg_facets(db_path=db_path)


# ==========================================
# [O] Hierarchical Topic Taxonomy & Routing
# ==========================================

from app.topic import (
    list_topics as _list_topics,
    search_by_topic as _search_by_topic,
    detect_query_topics as _detect_query_topics,
)


def list_knowledge_topics(db_path: Path | str | None = None) -> List[Dict[str, Any]]:
    """Lists all auto-extracted hierarchical topics and chunk associations."""
    return _list_topics(db_path=db_path)


def search_knowledge_by_topic(topic: str, query: str, limit: int = 3, db_path: Path | str | None = None) -> str:
    """Restricts semantic search to a specific topic subgraph to eliminate domain drift."""
    results = _search_by_topic(topic=topic, query=query, limit=limit, db_path=db_path)
    if not results:
        return f"No documentation found in topic '{topic}' matching query '{query}'."

    lines = [f"Topic Subgraph Results for [{topic}] - '{query}':\n"]
    for r in results:
        lines.append(f"- [{r['doc_id']}] (Score: {r['score']:.4f}):\n  {r['content'][:300]}")
    return "\n".join(lines)


# ==========================================
# [A] AutoKarpathy Self-Distillation & Evals
# ==========================================

from app.autokarpathy import (
    autokarpathy_generate_synthetic_dataset as _gen_dataset,
    autokarpathy_optimize_prompt as _opt_prompt,
    autokarpathy_eval_cartridge as _eval_cartridge,
)


def generate_synthetic_dataset(output_path: str = "", db_path: Path | str | None = None) -> Dict[str, Any]:
    """AutoKarpathy: Synthesizes instruction-tuning pairs from knowledge and successful trajectories."""
    p = Path(output_path) if output_path else None
    return _gen_dataset(output_path=p, db_path=db_path)


def optimize_agent_prompt(task_description: str, base_prompt: str = "", db_path: Path | str | None = None) -> Dict[str, Any]:
    """AutoKarpathy: Compresses and sharpens system prompt constraints for local LLMs."""
    return _opt_prompt(task_description=task_description, base_prompt=base_prompt, db_path=db_path)


def evaluate_cartridge_health(db_path: Path | str | None = None) -> Dict[str, Any]:
    """AutoKarpathy: Computes benchmark health and factuality scores across ROMS."""
    return _eval_cartridge(db_path=db_path)


# ==========================================
# [A] AutoResearch Deep Investigation Engine
# ==========================================

from app.autoresearch import (
    execute_autoresearch as _execute_autoresearch,
)


def run_autoresearch(
    topic: str,
    depth: int = 2,
    max_sources: int = 6,
    save_to_knowledge: bool = True,
    output_dir: Optional[Path | str] = None,
    db_path: Path | str | None = None,
) -> Dict[str, Any]:
    """AutoResearch: Conducts multi-hop research, compiles verified dossier, and compounds into knowledge."""
    return _execute_autoresearch(
        topic=topic,
        depth=depth,
        max_sources=max_sources,
        save_to_knowledge=save_to_knowledge,
        output_dir=output_dir,
        db_path=db_path,
    )




