"""Offline tool performance regressions; no model, network, or live database."""
import json
import sqlite3
import statistics
from unittest.mock import patch
import time

import psutil

from app import tools, tool_rag
from app.db import get_connection, init_database


def test_system_metrics_uses_one_database_read(tmp_path, monkeypatch):
    database = tmp_path / "metrics.db"
    init_database(database)
    connection = get_connection(database, reuse=False)
    connection.executemany(
        "INSERT INTO okf_registry (doc_id, title, doc_type, checksum) VALUES (?, ?, ?, ?)",
        [("one.md", "One", "guide", "a"), ("two.md", "Two", "policy", "b")],
    )
    connection.execute(
        "INSERT INTO embedding_cache (query_hash, embedding_blob) VALUES (?, ?)", ("q", b"vector")
    )
    connection.execute(
        "INSERT INTO support_tickets (ticket_id, customer_email, issue_summary, status) "
        "VALUES ('open', 'a@example.test', 'issue', 'OPEN')"
    )
    connection.execute(
        "INSERT INTO support_tickets (ticket_id, customer_email, issue_summary, status) "
        "VALUES ('closed', 'b@example.test', 'issue', 'CLOSED')"
    )
    connection.commit()
    statements = []
    connection.set_trace_callback(statements.append)
    monkeypatch.setattr(tools, "get_connection", lambda *args, **kwargs: connection)
    monkeypatch.setattr(tools, "list_skills", lambda: ["one", "two"])
    monkeypatch.setattr(psutil, "cpu_percent", lambda interval=None: 12.5)
    monkeypatch.setattr(
        psutil,
        "virtual_memory",
        lambda: type("Memory", (), {"available": 2 * 1024**2, "total": 8 * 1024**2})(),
    )

    result = tools.get_system_metrics(database)

    reads = [statement for statement in statements if statement.lstrip().upper().startswith("SELECT")]
    assert len(reads) == 1
    assert result == {
        "host_cpu_percent": 12.5,
        "available_ram_mb": 2.0,
        "total_ram_mb": 8.0,
        "ingested_documents": 2,
        "indexed_chunks": 0,
        "cached_query_embeddings": 1,
        "registered_skills": 2,
        "open_tickets": 1,
    }


def test_tool_search_keeps_catalog_order_for_tied_scores(monkeypatch):
    catalog = [
        {
            "tool_name": name,
            "category": "general",
            "description": "ticket lookup",
            "parameters": {},
            "examples": [],
            "call_count": 0,
            "success_count": 0,
            "last_latency_ms": 0.0,
            "last_error": "",
            "searchable_text": "ticket lookup",
        }
        for name in ("first", "second", "third")
    ]
    monkeypatch.setattr(tool_rag, "_CATALOG_CACHE", {"fixture": catalog})
    monkeypatch.setattr(tool_rag, "_TOOL_SEARCH_CACHE", {})

    results = tool_rag.search_tools("ticket", limit=2, db_path="fixture", semantic=False)

    assert [item["tool_name"] for item in results] == ["first", "second"]
    assert all(item["score"] == 12.0 for item in results)


def test_tool_search_cache_has_a_bounded_size(monkeypatch):
    catalog = [{
        "tool_name": "ticket_tool",
        "category": "support",
        "description": "ticket lookup",
        "parameters": {},
        "examples": [],
        "call_count": 0,
        "success_count": 0,
        "last_latency_ms": 0.0,
        "last_error": "",
        "searchable_text": "ticket lookup",
    }]
    monkeypatch.setattr(tool_rag, "_CATALOG_CACHE", {"fixture": catalog})
    monkeypatch.setattr(tool_rag, "_TOOL_SEARCH_CACHE", {})
    monkeypatch.setattr(tool_rag, "_TOOL_SEARCH_CACHE_MAX", 2)

    for query in ("ticket", "lookup", "missing", "other"):
        tool_rag.search_tools(query, db_path="fixture", semantic=False)

    assert len(tool_rag._TOOL_SEARCH_CACHE) == 2
    assert "fixture::ticket::::3" not in tool_rag._TOOL_SEARCH_CACHE


def _legacy_tool_search(catalog, query, category="", limit=3):
    clean_q = query.strip().lower()
    clean_cat = category.strip().lower()
    query_tokens = set(clean_q.replace("_", " ").split())
    scored_tools = []
    for item in catalog:
        if clean_cat and item["category"].lower() != clean_cat:
            continue
        matches = sum(1 for token in query_tokens if token in item["searchable_text"])
        if matches == 0 and query_tokens:
            continue
        calls = item["call_count"]
        successes = item["success_count"]
        reliability = successes / calls if calls > 0 else 1.0
        scored_tools.append({
            "tool_name": item["tool_name"],
            "category": item["category"],
            "description": item["description"],
            "parameters": item["parameters"],
            "examples": item["examples"],
            "score": matches * 10.0 + reliability * 2.0,
            "call_count": calls,
            "reliability_pct": round(reliability * 100, 1),
            "last_latency_ms": round(item["last_latency_ms"], 2),
        })
    scored_tools.sort(key=lambda item: item["score"], reverse=True)
    return scored_tools[:limit]


def run_tool_search_benchmark():
    """Profiles a cold catalog scan and top-three ranking on a fixed local fixture."""
    catalog = [
        {
            "tool_name": f"ticket_tool_{index}",
            "category": "support",
            "description": f"Ticket processing workflow {index}",
            "parameters": {},
            "examples": [],
            "call_count": 0,
            "success_count": 0,
            "last_latency_ms": 0.0,
            "last_error": "",
            "searchable_text": f"ticket_tool_{index} support ticket processing workflow {index}",
        }
        for index in range(20000)
    ]
    tool_rag._CATALOG_CACHE["benchmark"] = catalog
    timings = {"legacy_median_ms": [], "optimized_median_ms": []}
    with patch.object(tool_rag, "_CATALOG_CACHE", {"benchmark": catalog}):
        assert tool_rag.search_tools("ticket processing", limit=3, db_path="benchmark", semantic=False) == _legacy_tool_search(
            catalog, "ticket processing", limit=3
        )
        for _ in range(7):
            start = time.perf_counter_ns()
            for _ in range(20):
                results = _legacy_tool_search(catalog, "ticket processing", limit=3)
                assert len(results) == 3
            timings["legacy_median_ms"].append((time.perf_counter_ns() - start) / 20 / 1_000_000)

            start = time.perf_counter_ns()
            for _ in range(20):
                tool_rag._TOOL_SEARCH_CACHE.clear()
                results = tool_rag.search_tools("ticket processing", limit=3, db_path="benchmark", semantic=False)
                assert len(results) == 3
            timings["optimized_median_ms"].append((time.perf_counter_ns() - start) / 20 / 1_000_000)

    print(json.dumps({
        "benchmark": "tool-search-20k-catalog-top-3",
        "legacy_median_ms": statistics.median(timings["legacy_median_ms"]),
        "optimized_median_ms": statistics.median(timings["optimized_median_ms"]),
        "legacy_batches_ms": timings["legacy_median_ms"],
        "optimized_batches_ms": timings["optimized_median_ms"],
    }, indent=2))
    tool_rag._CATALOG_CACHE.pop("benchmark", None)
    tool_rag._TOOL_SEARCH_CACHE.clear()
