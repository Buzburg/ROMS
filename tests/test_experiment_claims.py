"""Experimental helpers must distinguish recorded counts from measured quality."""

import json

import pytest

from app.autokarpathy import (
    autokarpathy_eval_cartridge,
    autokarpathy_generate_synthetic_dataset,
    autokarpathy_optimize_prompt,
)
from app.db import get_connection, init_database


@pytest.fixture
def inventory_db(tmp_path):
    path = tmp_path / "inventory.db"
    init_database(path)
    try:
        yield path
    finally:
        get_connection(path).close()


@pytest.mark.parametrize("base_prompt", ["", "Keep this exact refund policy: return within 30 days.\nUse \u20ac for prices."])
def test_prompt_growth_does_not_claim_reduction_or_evaluated_quality(inventory_db, base_prompt):
    result = autokarpathy_optimize_prompt("Review the refund policy", base_prompt, db_path=inventory_db)

    assert result["prepared_prompt_characters"] == len(result["optimized_prompt"])
    assert result["base_prompt_characters"] == len(base_prompt)
    assert result["prepared_prompt_characters"] > result["base_prompt_characters"]
    assert base_prompt in result["optimized_prompt"]
    assert result["token_reduction_est_pct"] is None
    assert result["evaluation_status"] == "not_evaluated"
    assert json.loads(json.dumps(result))["token_reduction_est_pct"] is None

    stored = get_connection(inventory_db).execute(
        "SELECT prompt, score, feedback FROM karpathy_evals WHERE eval_id = ?", (result["eval_id"],)
    ).fetchone()
    assert stored[0] == result["optimized_prompt"]
    assert stored[1] is None
    assert "not measured" in stored[2]


def test_empty_inventory_reports_no_observed_success_rate(inventory_db):
    result = autokarpathy_eval_cartridge(inventory_db)
    assert result["total_trajectories"] == 0
    assert result["indexed_knowledge_chunks"] == 0
    assert result["trajectory_success_rate_pct"] is None
    assert result["overall_cartridge_health_score"] is None
    assert result["benchmark_engine"] is None
    assert result["evaluation_status"] == "not_evaluated"


@pytest.mark.parametrize(("success_flags", "expected_rate"), [([1, 1], 100.0), ([1, 0], 50.0), ([0, 0], 0.0)])
def test_recorded_outcomes_are_counts_without_a_model_health_score(inventory_db, success_flags, expected_rate):
    connection = get_connection(inventory_db)
    connection.executemany(
        "INSERT INTO agent_trajectories(session_id, success) VALUES (?, ?)",
        [(str(index), flag) for index, flag in enumerate(success_flags)],
    )
    connection.execute("INSERT INTO topics(topic_id, label) VALUES ('refund', 'Refund policy')")
    connection.executemany("INSERT INTO tool_stats(tool_name, call_count) VALUES (?, ?)", [("used", 2), ("unused", 0)])
    connection.commit()

    result = autokarpathy_eval_cartridge(inventory_db)
    assert result["total_trajectories"] == len(success_flags)
    assert result["trajectory_success_rate_pct"] == expected_rate
    assert result["hierarchical_topics"] == 1
    assert result["active_mcp_tools"] == 1
    assert result["overall_cartridge_health_score"] is None
    assert result["benchmark_engine"] is None
    assert result["evaluation_status"] == "not_evaluated"
    assert "caller-recorded" in result["measurement_scope"]


def test_dataset_counts_only_examples_actually_written(inventory_db, tmp_path):
    connection = get_connection(inventory_db)
    connection.execute("INSERT INTO okf_registry(doc_id, title, doc_type) VALUES ('refund.md', 'Refund policy', 'policy')")
    connection.executemany("INSERT INTO fts_chunks(chunk_id, doc_id, content) VALUES (?, 'refund.md', ?)",
                           [(1, "Too short"), (2, "Refunds require a receipt and must be requested within 30 days of purchase.")])
    connection.executemany(
        "INSERT INTO agent_trajectories(session_id, goal, steps_json, final_result, success) VALUES (?, 'Review refund', ?, 'Recorded result', 1)",
        [("complete", '[{"action": "check_receipt"}]'), ("empty", '[]')],
    )
    connection.commit()
    target = tmp_path / "examples.jsonl"

    result = autokarpathy_generate_synthetic_dataset(target, db_path=inventory_db)
    entries = [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines()]
    assert result["total_examples"] == len(entries) == 2
    assert result["knowledge_examples"] == 1
    assert result["trajectory_examples"] == 1
    assert "verified documentation" not in entries[0]["instruction"]
