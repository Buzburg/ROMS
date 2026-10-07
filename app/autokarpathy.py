"""Dataset export, prompt templates and local database inventory.

Legacy function names are retained for callers. These helpers do not train a
model, measure prompt quality or run factuality and perplexity benchmarks.
"""

import json
import uuid
from pathlib import Path
from typing import Any, Dict, Optional
from app.db import get_connection


def autokarpathy_generate_synthetic_dataset(
    output_path: Optional[Path | str] = None,
    min_tokens: int = 15,
    db_path: Path | str | None = None,
) -> Dict[str, Any]:
    """Export indexed text and trajectories marked successful as JSONL examples.

    Source labels and recorded success flags are not independent verification;
    exported examples need review before any training use.
    """
    target_file = Path(output_path) if output_path else Path("data/karpathy_synthetic_dataset.jsonl")
    target_file.parent.mkdir(parents=True, exist_ok=True)

    conn = get_connection(db_path)
    cur = conn.cursor()

    dataset_entries = []

    # 1. Synthesize Question-Answer pairs from Ingested Knowledge Chunks
    cur.execute("SELECT f.chunk_id, f.doc_id, f.content, r.title, r.doc_type FROM fts_chunks f JOIN okf_registry r ON f.doc_id = r.doc_id")
    chunks = cur.fetchall()

    for chunk_id, doc_id, content, title, doc_type in chunks:
        clean_content = content.strip()
        if len(clean_content) < min_tokens * 4:
            continue

        first_line = clean_content.splitlines()[0].replace("#", "").strip()
        instruction = f"Explain the specifications and policies regarding '{first_line}' based on supplied documentation."

        entry = {
            "id": f"rag_{chunk_id}",
            "instruction": instruction,
            "input": f"Source: {title} ({doc_type})",
            "output": clean_content,
            "source_type": "grounded_knowledge",
        }
        dataset_entries.append(entry)

    knowledge_examples = len(dataset_entries)

    # 2. Synthesize Action Pairs from Successful Agent Trajectories
    cur.execute("SELECT session_id, goal, steps_json, final_result FROM agent_trajectories WHERE success = 1")
    trajs = cur.fetchall()

    for session_id, goal, steps_json, final_result in trajs:
        try:
            steps = json.loads(steps_json) if steps_json else []
        except Exception:
            continue

        if not steps or not final_result:
            continue

        tools_seq = " -> ".join([s.get("action", "") for s in steps])
        instruction = f"Execute multi-step workflow to achieve: {goal}"
        solution_plan = f"Procedural Tool Chain: {tools_seq}\nExecution Result: {final_result}"

        entry = {
            "id": f"traj_{session_id}",
            "instruction": instruction,
            "input": f"Goal: {goal}",
            "output": solution_plan,
            "source_type": "verified_trajectory",
        }
        dataset_entries.append(entry)

    # Write JSONL file
    with open(target_file, "w", encoding="utf-8") as f:
        for item in dataset_entries:
            f.write(json.dumps(item) + "\n")

    return {
        "status": "success",
        "output_file": str(target_file.resolve()),
        "total_examples": len(dataset_entries),
        "knowledge_examples": knowledge_examples,
        "trajectory_examples": len(dataset_entries) - knowledge_examples,
    }


def autokarpathy_optimize_prompt(
    task_description: str,
    base_prompt: str = "",
    db_path: Path | str | None = None,
) -> Dict[str, Any]:
    """Prepare and record a prompt template without evaluating improvement."""
    eval_id = str(uuid.uuid4())[:8]

    # These are instructions for a caller, not measured or enforced guarantees.
    refined_lines = [
        "ROLE: Deterministic System Operator.",
        f"OBJECTIVE: {task_description.strip()}",
        "",
        "OPERATIONAL CONSTRAINTS:",
        "1. Never guess or hallucinate parameters; verify against provided <knowledge_context> or <available_mcp_tools>.",
        "2. Keep output token-efficient and bounded.",
        "3. If information is missing, request clarification or return structured error.",
    ]
    if base_prompt:
        refined_lines.append(f"\nBASE INSTRUCTIONS:\n{base_prompt.strip()}")

    optimized_prompt = "\n".join(refined_lines)

    # Retain the existing history table without inventing an evaluation score.
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO karpathy_evals (eval_id, task_name, prompt, score, feedback)
        VALUES (?, ?, ?, ?, ?)
        """,
        (eval_id, task_description[:50], optimized_prompt, None,
         "Prompt template prepared; token reduction and quality improvement were not measured."),
    )
    conn.commit()

    return {
        "eval_id": eval_id,
        "task": task_description,
        "optimized_prompt": optimized_prompt,
        "token_reduction_est_pct": None,
        "evaluation_status": "not_evaluated",
        "base_prompt_characters": len(base_prompt),
        "prepared_prompt_characters": len(optimized_prompt),
        "measurement_scope": "Character counts only; no tokenizer, model or quality evaluation was run.",
    }


def autokarpathy_eval_cartridge(db_path: Path | str | None = None) -> Dict[str, Any]:
    """Report stored counts and recorded success flags, without a quality score."""
    conn = get_connection(db_path)
    cur = conn.cursor()

    cur.execute("SELECT count(*) FROM vec_chunks")
    total_chunks = cur.fetchone()[0]

    cur.execute("SELECT count(*) FROM agent_trajectories")
    total_trajs = cur.fetchone()[0]

    cur.execute("SELECT count(*) FROM agent_trajectories WHERE success = 1")
    succ_trajs = cur.fetchone()[0]

    cur.execute("SELECT count(*) FROM topics")
    total_topics = cur.fetchone()[0]

    cur.execute("SELECT count(*) FROM tool_stats WHERE call_count > 0")
    active_tools = cur.fetchone()[0]

    trajectory_success_rate = round(succ_trajs / total_trajs * 100.0, 1) if total_trajs else None

    return {
        "overall_cartridge_health_score": None,
        "indexed_knowledge_chunks": total_chunks,
        "hierarchical_topics": total_topics,
        "active_mcp_tools": active_tools,
        "total_trajectories": total_trajs,
        "trajectory_success_rate_pct": trajectory_success_rate,
        "benchmark_engine": None,
        "evaluation_status": "not_evaluated",
        "measurement_scope": "Database inventory and caller-recorded success flags only; no outcomes were independently verified.",
    }
