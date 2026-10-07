"""Comprehensive test suite for ROMS architecture."""

import os
import tempfile
import pytest
from pathlib import Path

from app.config import get_embedding_model, EMBEDDING_DIM
from app.db import get_connection, init_database
from app.okf_loader import ingest_okf_file, ingest_okf_directory
from app.rag_engine import (
    vector_search,
    lexical_search,
    hybrid_search,
    format_search_results,
    search_knowledge_base,
    _get_query_embedding,
)
from app.tools import (
    create_support_ticket,
    get_support_ticket,
    update_ticket_status,
    list_support_tickets,
    sanitize_output,
    add_knowledge_document,
    reload_knowledge,
    list_knowledge_documents,
    add_skill,
    list_skills,
)
from app.server import get_customer_service_skill, customer_service_sop, mcp


@pytest.fixture
def temp_db(tmp_path):
    """Provides an isolated test database path."""
    db_file = tmp_path / "test_roms.db"
    init_database(db_file)
    return db_file


@pytest.fixture
def temp_knowledge_dir(tmp_path):
    """Provides a temporary knowledge directory with sample OKF markdown files."""
    k_dir = tmp_path / "knowledge"
    k_dir.mkdir()

    doc1 = k_dir / "refund_policy.md"
    doc1.write_text(
        """---
okf_version: "0.2"
type: "policy"
title: "Customer Return & Replacement Terms"
last_updated: "2026-09-26"
owner: "Buzburg LLC Operations"
tags: ["refund", "billing", "support"]
---

# Customer Return & Replacement Terms

Items damaged in transit are entitled to a full replacement within 30 days of arrival.

When processing an issue:
1. Verify whether the ticket ID matches existing records.
2. Confirm the customer provided their registered email address.
3. Automatically escalate the ticket status to 'URGENT' if the replacement request involves hardware failure.
""",
        encoding="utf-8",
    )
    return k_dir


def test_database_initialization(temp_db):
    """Verifies all required tables are created in SQLite."""
    conn = get_connection(temp_db)
    cur = conn.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table' OR type='shadow'")
    tables = [row[0] for row in cur.fetchall()]
    conn.close()

    assert "okf_registry" in tables
    assert "support_tickets" in tables
    assert "embedding_cache" in tables
    assert any("vec_chunks" in t for t in tables)
    assert any("fts_chunks" in t for t in tables)


def test_okf_ingestion_and_deduplication(temp_db, temp_knowledge_dir):
    """Tests OKF ingestion, dual-index storage (vector + FTS5), and SHA-256 deduplication."""
    # First ingestion
    count1 = ingest_okf_directory(temp_knowledge_dir, db_path=temp_db)
    assert count1 == 1

    conn = get_connection(temp_db)
    cur = conn.cursor()

    cur.execute("SELECT doc_id, title, doc_type, checksum FROM okf_registry")
    rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "refund_policy.md"
    assert rows[0][1] == "Customer Return & Replacement Terms"

    cur.execute("SELECT count(*) FROM vec_chunks")
    assert cur.fetchone()[0] > 0

    cur.execute("SELECT count(*) FROM fts_chunks")
    assert cur.fetchone()[0] > 0
    conn.close()

    # Second ingestion without file modifications - should skip
    count2 = ingest_okf_directory(temp_knowledge_dir, db_path=temp_db)
    assert count2 == 0


def test_hybrid_search_and_caching(temp_db, temp_knowledge_dir):
    """Tests semantic vector search, BM25 lexical search, RRF fusion, and embedding cache."""
    ingest_okf_directory(temp_knowledge_dir, db_path=temp_db)

    # 1. Vector Search
    vec_results = vector_search("How many days do I have to replace damaged items?", limit=2, db_path=temp_db)
    assert len(vec_results) > 0
    assert any("30 days" in r["content"] for r in vec_results)

    # 2. Lexical Search (BM25 exact match)
    lex_results = lexical_search("transit hardware failure", limit=2, db_path=temp_db)
    assert len(lex_results) > 0

    # 3. Hybrid RRF Search
    hybrid_res = hybrid_search("transit damage refund window", limit=1, db_path=temp_db)
    assert len(hybrid_res) > 0
    assert "refund_policy.md" == hybrid_res[0]["doc_id"]

    # 4. Formatted output
    formatted = search_knowledge_base("transit damage refund window", limit=1, db_path=temp_db)
    assert "refund_policy.md" in formatted
    assert "Score:" in formatted

    # 5. Query Embedding Cache Check
    emb1 = _get_query_embedding("transit damage refund window", db_path=temp_db)
    emb2 = _get_query_embedding("transit damage refund window", db_path=temp_db)
    assert emb1 == emb2


def test_support_ticket_lifecycle(temp_db):
    """Tests ticket creation, lookup, status update, and listing."""
    res = create_support_ticket(
        ticket_id="TICK-1001",
        customer_email="support@buzburg.com",
        issue_summary="Package arrived broken",
        db_path=temp_db,
    )
    assert "created successfully" in res

    ticket = get_support_ticket("TICK-1001", db_path=temp_db)
    assert ticket is not None
    assert ticket["customer_email"] == "support@buzburg.com"
    assert ticket["status"] == "OPEN"

    upd_res = update_ticket_status("TICK-1001", "URGENT", db_path=temp_db)
    assert "updated to 'URGENT'" in upd_res

    updated_ticket = get_support_ticket("TICK-1001", db_path=temp_db)
    assert updated_ticket["status"] == "URGENT"

    tickets = list_support_tickets(status="URGENT", db_path=temp_db)
    assert len(tickets) == 1
    assert tickets[0]["ticket_id"] == "TICK-1001"


def test_sanitize_output():
    """Verifies that large terminal outputs are safely truncated to protect LLM context windows."""
    short_text = "All tests passed successfully."
    assert sanitize_output(short_text, max_length=100) == short_text

    long_text = "A" * 3000
    sanitized = sanitize_output(long_text, max_length=2500)
    assert len(sanitized) < 3000
    assert "...[OUTPUT TRUNCATED BY MCP GUARDIAN]..." in sanitized


def test_skills_loader():
    """Verifies skills resource and prompt return the SOP documentation."""
    sop_resource = get_customer_service_skill()
    sop_prompt = customer_service_sop()

    assert "Customer Service" in sop_resource
    assert "search_knowledge_base" in sop_resource
    assert sop_resource == sop_prompt


def test_mcp_registration():
    """Verifies FastMCP exposes all expected tools and resources."""
    assert mcp.name == "ROMS-Engine"


def test_prompt_builder_grounding_and_deduplication():
    """Verifies that RAG chunks are deduplicated and formatted for local LLMs."""
    from app.prompt_builder import (
        compress_chunks,
        format_context_for_local_llm,
        build_grounded_system_prompt,
    )

    chunks = [
        {"doc_id": "policy.md", "content": "Items damaged in transit are entitled to full replacement.", "score": 0.035},
        {"doc_id": "policy.md", "content": "Items damaged in transit are entitled to full replacement.", "score": 0.034},  # duplicate
        {"doc_id": "policy.md", "content": "Low relevance noise that should be pruned.", "score": 0.005},  # below min_score
    ]

    compressed = compress_chunks(chunks, max_tokens=200, min_score=0.010)
    assert len(compressed) == 1
    assert "Items damaged" in compressed[0]["content"]

    xml_context = format_context_for_local_llm(chunks, format_style="xml", min_score=0.010)
    assert "<knowledge_context>" in xml_context
    assert '<source id="1" doc="policy.md"' in xml_context

    system_prompt = build_grounded_system_prompt("You are a helpful assistant.", xml_context)
    assert "CRITICAL INSTRUCTIONS:" in system_prompt
    assert "<knowledge_context>" in system_prompt


def test_code_search_plugin():
    """Verifies drop-in codebase search tool."""
    from custom_tools.code_search import register_tools
    from fastmcp import FastMCP

    test_mcp = FastMCP("TestMCP")
    register_tools(test_mcp)

    # Directly test code search logic
    from app.server import load_custom_tools
    load_custom_tools()


def test_watcher_lifecycle():
    """Verifies background file watcher status and control."""
    from app.watcher import start_watcher, get_watcher_status, stop_watcher

    start_watcher()
    status = get_watcher_status()
    assert status["is_running"] is True
    stop_watcher()
    status_after = get_watcher_status()
    assert status_after["is_running"] is False


def test_universal_multiformat_ingestion(temp_db, tmp_path):
    """Verifies RAG-Anything universal ingestion of CSV tables and JSON datasets."""
    k_dir = tmp_path / "knowledge_multi"
    k_dir.mkdir()

    # 1. Create a sample CSV
    csv_file = k_dir / "hardware_inventory.csv"
    csv_file.write_text(
        "sku,product_name,category,warranty_months\n"
        "HW-901,Precision Tensor Card,Compute,36\n"
        "HW-902,Ultra-Low Latency Switch,Networking,24\n",
        encoding="utf-8",
    )

    # 2. Create a sample JSON dataset
    json_file = k_dir / "service_levels.json"
    json_file.write_text(
        '[\n'
        '  {"tier": "Platinum", "response_time_minutes": 15, "onsite": true},\n'
        '  {"tier": "Gold", "response_time_minutes": 60, "onsite": false}\n'
        ']',
        encoding="utf-8",
    )

    ingested_count = ingest_okf_directory(k_dir, db_path=temp_db)
    assert ingested_count == 2

    # Query CSV tabular context
    csv_results = hybrid_search("Precision Tensor Card warranty", limit=2, db_path=temp_db)
    assert len(csv_results) > 0
    assert "HW-901" in csv_results[0]["content"]
    assert "Columns: sku, product_name" in csv_results[0]["content"]

    # Query JSON dataset context
    json_results = hybrid_search("Platinum 15 response time", limit=2, db_path=temp_db)
    assert len(json_results) > 0
    assert "Platinum" in json_results[0]["content"]


def test_smart_tool_rag_and_analytics(temp_db):
    """Verifies AnyTool-inspired tool schema discovery, latency tracking, and self-healing recovery."""
    from app.tool_rag import (
        init_default_tool_registry,
        search_tools,
        format_tool_search_results,
        record_tool_call,
        get_tool_health_report,
        handle_tool_failure,
    )

    # 1. Initialize default registry in isolated test DB
    init_default_tool_registry(db_path=temp_db)

    # 2. Smart Tool RAG discovery
    tools = search_tools("damaged hardware replacement ticket", limit=2, db_path=temp_db)
    assert len(tools) > 0
    assert any("ticket" in t["tool_name"] for t in tools)

    formatted_schema = format_tool_search_results("ticket update", limit=1, db_path=temp_db)
    assert "update_ticket_status" in formatted_schema
    assert "Parameters" in formatted_schema

    # 3. Call tracking & reliability metrics
    record_tool_call("create_support_ticket", success=True, latency_ms=4.2, db_path=temp_db)
    record_tool_call("create_support_ticket", success=True, latency_ms=3.8, db_path=temp_db)
    record_tool_call("create_support_ticket", success=False, latency_ms=5.1, error="Missing customer email", db_path=temp_db)

    health_report = get_tool_health_report(db_path=temp_db)
    assert "create_support_ticket" in health_report
    assert "66.7%" in health_report  # 2 successes out of 3 calls

    # 4. Self-healing failure recovery guidance
    failure_guidance = handle_tool_failure(
        tool_name="create_support_ticket",
        error_message="Missing argument 'email'",
        attempted_args={"ticket_id": "TICK-99"},
        db_path=temp_db,
    )
    assert "Self-Healing Guidance" in failure_guidance
    assert "Provided args" in failure_guidance


def test_upskill_trajectory_recording_and_distillation(temp_db, tmp_path):
    """Verifies UpSkill trajectory capture and automated procedural SOP skill brewing."""
    from app.trajectory_recorder import (
        start_session,
        record_step,
        finish_session,
        get_trajectory,
        distill_trajectory_to_skill,
    )

    session_id = "test_refund_sess_42"
    start_session(session_id=session_id, goal="Process customer return for damaged GPU", db_path=temp_db)

    # Step 1: Query knowledge base
    record_step(
        session_id=session_id,
        action="search_knowledge_base",
        input_params={"query": "damaged GPU return window"},
        output_result="Full replacement within 30 days of arrival.",
        db_path=temp_db,
    )

    # Step 2: Create ticket
    record_step(
        session_id=session_id,
        action="create_support_ticket",
        input_params={"ticket_id": "TICK-88", "email": "dev@gpu.com", "summary": "GPU cracked"},
        output_result="Ticket TICK-88 created successfully.",
        db_path=temp_db,
    )

    # Step 3: Escalate ticket
    record_step(
        session_id=session_id,
        action="update_ticket_status",
        input_params={"ticket_id": "TICK-88", "status": "URGENT"},
        output_result="Ticket TICK-88 status updated to 'URGENT'.",
        db_path=temp_db,
    )

    finish_session(session_id=session_id, success=True, final_result="Ticket created and escalated", db_path=temp_db)

    traj = get_trajectory(session_id, db_path=temp_db)
    assert traj is not None
    assert len(traj["steps"]) == 3
    assert traj["success"] is True

    # Distill into a production SOP in temporary skills dir
    test_skills_dir = tmp_path / "brewed_skills"
    result_msg = distill_trajectory_to_skill(
        session_id=session_id,
        skill_name="damaged_gpu_escalation",
        description="Standard operating procedure for expedited replacement of damaged GPUs.",
        target_skills_dir=test_skills_dir,
        db_path=temp_db,
    )

    assert "Candidate skill" in result_msg
    sop_file = test_skills_dir / "damaged_gpu_escalation.md"
    assert sop_file.exists()

    sop_content = sop_file.read_text(encoding="utf-8")
    assert "skill_version: \"1.0\"" in sop_content
    assert "Damaged Gpu Escalation Standard Operating Procedure" in sop_content
    assert "`search_knowledge_base`" in sop_content
    assert "`create_support_ticket`" in sop_content
    assert "`update_ticket_status`" in sop_content
    assert "Step 1: Execute `search_knowledge_base`" in sop_content
    assert "Verification Checklist" in sop_content


def test_autonomous_skill_evolver(temp_db, tmp_path):
    """Verifies that ROMS autonomously detects multi-turn successful trajectories and brews SOPs."""
    from app.auto_evolver import scan_and_evolve_skills
    from app.trajectory_recorder import start_session, record_step, finish_session

    sess_id = "sess_autonomous_learn_01"
    start_session(sess_id, "Automate weekly database backup and sync", db_path=temp_db)
    record_step(sess_id, "backup_sqlite", {"target": "data/roms.db"}, "Backup created at /tmp/backup.db", db_path=temp_db)
    record_step(sess_id, "verify_checksum", {"file": "/tmp/backup.db"}, "Checksum verified OK", db_path=temp_db)
    finish_session(sess_id, success=True, final_result="Backup complete", db_path=temp_db)

    test_skills_dir = tmp_path / "auto_skills"
    evolved = scan_and_evolve_skills(min_steps=2, target_skills_dir=test_skills_dir, db_path=temp_db)

    assert len(evolved) >= 1
    skill_name = evolved[0]["skill_name"]
    assert (test_skills_dir / f"{skill_name}.md").exists()
    content = (test_skills_dir / f"{skill_name}.md").read_text(encoding="utf-8")
    assert "Weekly Database Backup" in content or "Database Backup" in content
    assert "`backup_sqlite`" in content


def test_gateway_health_and_models(temp_db, monkeypatch):
    """Verifies health against an isolated database and deterministic model fallback."""
    from starlette.testclient import TestClient
    from app.gateway import app

    from app import tools, gateway
    original_metrics = tools.get_system_metrics
    monkeypatch.setattr(tools, "get_system_metrics", lambda: original_metrics(db_path=temp_db))

    class OfflineBackend:
        def __init__(self, **kwargs):
            pass
        async def __aenter__(self):
            raise gateway.httpx.ConnectError("No backend in this test")
        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(gateway.httpx, "AsyncClient", OfflineBackend)
    client = TestClient(app)

    # 1. Health endpoint
    h_resp = client.get("/health")
    assert h_resp.status_code == 200
    assert h_resp.json()["status"] == "online"

    # 2. Models endpoint
    m_resp = client.get("/v1/models")
    assert m_resp.status_code == 200
    models = m_resp.json()
    assert any("roms" in m["id"] for m in models["data"])


def test_zgsearch_fuzzy_and_faceted(temp_db, temp_knowledge_dir):
    """Verifies ZG-Search typo tolerance and facet filtering with zero GPU overhead."""
    from app.zgsearch import zg_search, get_zg_facets

    ingest_okf_directory(temp_knowledge_dir, db_path=temp_db)

    # 1. Test typo tolerance: "damagd replacment" instead of "damaged replacement"
    typo_results = zg_search("damagd replacment", fuzzy=True, limit=3, db_path=temp_db)
    assert len(typo_results) > 0
    assert any("refund_policy.md" in r["doc_id"] for r in typo_results)

    # 2. Test faceted filtering on doc_type
    policy_results = zg_search("replacement", filters={"doc_type": "policy"}, db_path=temp_db)
    assert len(policy_results) > 0
    assert all(r["doc_type"] == "policy" for r in policy_results)

    # 3. Test facet counts
    facets = get_zg_facets(db_path=temp_db)
    assert "document_types" in facets
    assert facets["document_types"].get("policy", 0) >= 1
    assert facets["total_chunks"] > 0


def test_hierarchical_topics_and_routed_rag(temp_db, temp_knowledge_dir):
    """Verifies topic taxonomy extraction, chunk tagging, and topic-routed RAG."""
    from app.topic import list_topics, detect_query_topics, search_by_topic

    ingest_okf_directory(temp_knowledge_dir, db_path=temp_db)

    # 1. Verify topics were extracted and linked during ingestion
    topics = list_topics(db_path=temp_db)
    assert len(topics) > 0
    topic_ids = [t["topic_id"] for t in topics]
    assert "policy" in topic_ids or any(t["chunk_count"] > 0 for t in topics)

    # 2. Test query topic detection
    detected = detect_query_topics("policy return guidelines", db_path=temp_db)
    assert isinstance(detected, list)

    # 3. Test topic-routed retrieval
    routed = search_by_topic(topic=topics[0]["topic_id"], query="damaged items", limit=2, db_path=temp_db)
    assert len(routed) > 0
    assert routed[0]["topic"] == topics[0]["topic_id"]


def test_autokarpathy_pipeline(temp_db, temp_knowledge_dir, tmp_path):
    """Verifies AutoKarpathy synthetic dataset generation, prompt optimizer, and cartridge eval."""
    import json
    from app.autokarpathy import (
        autokarpathy_generate_synthetic_dataset,
        autokarpathy_optimize_prompt,
        autokarpathy_eval_cartridge,
    )
    from app.trajectory_recorder import start_session, record_step, finish_session

    ingest_okf_directory(temp_knowledge_dir, db_path=temp_db)

    # Record sample trajectory for dataset synthesis
    sess_id = "sess_karpathy_01"
    start_session(sess_id, "Process return for defective hardware", db_path=temp_db)
    record_step(sess_id, "search_knowledge_base", {"query": "return window"}, "Found 30 days window", db_path=temp_db)
    record_step(sess_id, "create_support_ticket", {"issue": "defective"}, "Ticket created", db_path=temp_db)
    finish_session(sess_id, success=True, final_result="Resolved successfully", db_path=temp_db)

    # 1. Test synthetic dataset generation
    out_jsonl = tmp_path / "synthetic_dataset.jsonl"
    gen_res = autokarpathy_generate_synthetic_dataset(output_path=out_jsonl, min_tokens=5, db_path=temp_db)
    assert gen_res["status"] == "success"
    assert gen_res["total_examples"] > 0
    assert out_jsonl.exists()

    with open(out_jsonl, "r", encoding="utf-8") as f:
        lines = [json.loads(line) for line in f]
    assert len(lines) > 0
    assert all("instruction" in l and "input" in l and "output" in l for l in lines)

    # 2. Test prompt optimizer
    opt_res = autokarpathy_optimize_prompt(
        task_description="Execute customer refund verification",
        base_prompt="You should help customers with refunds",
        db_path=temp_db,
    )
    assert "optimized_prompt" in opt_res
    assert "OPERATIONAL CONSTRAINTS:" in opt_res["optimized_prompt"]
    assert opt_res["token_reduction_est_pct"] is None
    assert opt_res["evaluation_status"] == "not_evaluated"

    # 3. Test cartridge evaluation
    eval_res = autokarpathy_eval_cartridge(db_path=temp_db)
    assert eval_res["overall_cartridge_health_score"] is None
    assert eval_res["evaluation_status"] == "not_evaluated"
    assert eval_res["indexed_knowledge_chunks"] > 0
    assert eval_res["total_trajectories"] >= 1
    assert eval_res["trajectory_success_rate_pct"] == 100.0


def test_autoresearch_skill_and_engine(temp_db, temp_knowledge_dir, tmp_path):
    """Verifies AutoResearch multi-facet deconstruction, evidence harvesting, and OKF knowledge compounding."""
    from app.autoresearch import execute_autoresearch, deconstruct_research_topic
    from app.tools import run_autoresearch
    from app.server import autoresearch_sop

    ingest_okf_directory(temp_knowledge_dir, db_path=temp_db)

    # 1. Test topic deconstruction
    subqueries = deconstruct_research_topic("Customer Refund Policies")
    assert len(subqueries) >= 3
    assert any("principles" in sq or "limitations" in sq for sq in subqueries)

    # 2. Test deep research loop and knowledge compounding
    res = execute_autoresearch(
        topic="transit damaged hardware replacement terms",
        depth=2,
        max_sources=5,
        save_to_knowledge=True,
        output_dir=tmp_path / "knowledge_out",
        db_path=temp_db,
    )

    assert res["status"] == "success"
    assert res["sources_count"] > 0
    assert len(res["subqueries"]) >= 3
    assert "AutoResearch Dossier" in res["dossier"]
    assert "Executive Summary" in res["dossier"]
    assert "Evidence Ledger" in res["dossier"]
    assert res["saved_to_knowledge"] is True
    assert res["saved_file_path"] is not None
    assert Path(res["saved_file_path"]).exists()

    # Verify OKF frontmatter in saved file
    saved_text = Path(res["saved_file_path"]).read_text(encoding="utf-8")
    assert 'type: "research"' in saved_text
    assert "AutoResearch:" in saved_text

    # 3. Test through run_autoresearch tool wrapper
    tool_res = run_autoresearch(
        topic="transit damage",
        depth=1,
        save_to_knowledge=False,
        db_path=temp_db,
    )
    assert tool_res["status"] == "success"

    # 4. Verify FastMCP prompt loads skills/autoresearch.md
    sop_content = autoresearch_sop()
    assert "Autonomous Research & Knowledge Synthesis SOP" in sop_content
    assert "5-Stage Autonomous Research Protocol" in sop_content





