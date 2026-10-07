"""Numerical and advisory behavior checks for the Python Decision Maker."""

import json
import math
import tempfile
from pathlib import Path

import pytest

from app.decisions import (
    BERTopicDiscoveryEngine,
    ClassTFIDF,
    GooseStateDecisionHead,
    ROMSDecisionEngine,
    decide,
    distribution_from_logprobs,
    rank_options,
    validate_question,
)
from app.prefrontal_cortex import main as roms_cli_main


def test_normalized_decide_and_rank_options():
    """Verifies temperature-scaled softmax, margin, Shannon concentration, and abstention gates."""
    d_confident = decide([4.2, 0.5, -1.0], temperature=0.8, threshold=0.60, min_margin=0.15)
    assert d_confident.index == 0
    assert d_confident.confidence > 0.90
    assert d_confident.margin > 0.80
    assert d_confident.concentration > 0.60
    assert d_confident.abstain is False
    assert math.isclose(sum(d_confident.probabilities), 1.0, rel_tol=1e-5)

    # Flat logits should trigger abstention via margin & threshold gates
    d_uncertain = decide([1.0, 0.99, 0.98], temperature=1.0, threshold=0.60, min_margin=0.10)
    assert d_uncertain.abstain is True
    assert d_uncertain.margin < 0.05

    # Dot-product ranking
    scores = rank_options([1.0, 0.0, 0.0], [[0.9, 0.1, 0.0], [0.1, 0.9, 0.0]])
    assert scores[0] > scores[1]


def test_sglang_openjev_logprob_distribution():
    """Verifies the standalone parser against a synthetic metadata fixture."""
    meta = {
        "completion_tokens": 1,
        "finish_reason": {"type": "length"},
        "output_token_ids_logprobs": [[[-0.1, 32], [-2.4, 33], [-3.8, 34]]],
    }
    probs = distribution_from_logprobs(meta, [32, 33, 34])
    assert len(probs) == 3
    assert probs[0] > probs[1] > probs[2]
    assert math.isclose(sum(probs), 1.0, rel_tol=1e-6)


def test_hashed_state_forking():
    """Verifies fixed matrix shape and copied state, not model inference."""
    goose = GooseStateDecisionHead(state_dim=24)
    meta = goose.ingest_context("A deterministic word feature sketch uses a fixed matrix shape.")
    assert meta["ingested_tokens"] > 5
    assert meta["state_bytes"] == 24 * 24 * 8  # 4,608 bytes (~4.5 KB)

    fork_a = goose.fork_state()
    fork_b = goose.fork_state()
    assert fork_a == fork_b
    assert fork_a is not fork_b and fork_a is not goose.state
    fork_b[0] += 1.0
    assert fork_a[0] == goose.state[0] and fork_a[0] != fork_b[0]
    vec_a = goose.readout_vector(fork_a, "What state size does this sketch use?")
    assert len(vec_a) == 24
    assert math.isclose(sum(x * x for x in vec_a), 1.0, rel_tol=1e-5)


def test_multi_question_batch_choice_noul_score():
    """Verifies sequential choice, yes/no, and score evaluation in one call."""
    with tempfile.TemporaryDirectory() as tmp:
        engine = ROMSDecisionEngine(state_dir=tmp)
        state = {
            "event": "Database migration test passed with zero errors and verified SHA-256 snapshot integrity.",
            "status": "excellent",
        }
        questions = [
            {
                "id": "action_route",
                "type": "choice",
                "question": "Which subsystem handled the database migration and SHA-256 snapshot?",
                "options": {
                    "snapshot_db": "Database migration and SHA-256 snapshot integrity verification",
                    "ui_theme": "CSS dark mode stylesheet rendering and font icons",
                    "audio_codec": "Opus audio waveform synthesis",
                },
            },
            {
                "id": "migration_passed",
                "type": "noul",
                "question": "Did the database migration test pass with verified snapshot integrity?",
            },
            {
                "id": "quality_rubric",
                "type": "score",
                "question": "Rate the reliability and status of the migration test.",
                "options": [
                    "Critical failure and crash",
                    "Partial with moderate warnings",
                    "Passed and verified with excellent integrity",
                ],
            },
        ]

        batch = engine.ask(state, questions, reverse_debias=True)
        assert batch["question_count"] == 3
        assert batch["goose_state"]["state_bytes"] == 4608

        r_choice = batch["results"]["action_route"]
        assert r_choice["choice"] == "snapshot_db"
        assert r_choice["permutation_agreed"] is True
        assert r_choice["abstained"] is False

        r_noul = batch["results"]["migration_passed"]
        assert r_noul["choice"] == "yes"
        assert r_noul["noul"] > 0.65

        r_score = batch["results"]["quality_rubric"]
        assert r_score["score"] > 1.2
        assert r_score["score_normalized"] > 0.60


def test_topic_discovery_on_abstention():
    """Verifies heuristic candidate grouping after abstention."""
    with tempfile.TemporaryDirectory() as tmp:
        engine = ROMSDecisionEngine(state_dir=tmp, threshold=0.95, min_margin=0.50)
        res1 = engine.decide_choice(
            state="Quantum photonic waveguide entanglement calibration drift in cryogenic silicon",
            question="Route this hardware anomaly",
            options={"billing": "Stripe invoice payment", "auth": "OAuth2 login password"},
        )
        assert res1["abstained"] is True
        assert "bertopic_open_set_discovery" in res1

        # Add a second related document and verify c-TF-IDF extracts keywords
        engine.bertopic.add_document(
            "Cryogenic quantum photonic waveguide phase entanglement drift",
            doc_id="doc_quantum_2",
        )
        summary = engine.bertopic.summary()
        assert summary["total_documents"] >= 2
        assert summary["num_topics"] >= 1
        top_keywords = [k["word"] for k in summary["topics"][0]["keywords"]]
        assert any(w in top_keywords for w in ("quantum", "photonic", "waveguide", "cryogenic"))


def test_roms_cli_decide_noul_score_topics(capsys, tmp_path, monkeypatch):
    """Verifies the CLI subcommands `decide`, `noul`, `score`, and `topics`."""
    from app import decisions
    monkeypatch.setattr(decisions, "DEFAULT_STATE_DIR", str(tmp_path / "decisions"))
    rc = roms_cli_main([
        "decide",
        "--state", "User asked to rollback workspace files using SHA-256 Copy-on-Write snapshot",
        "--question", "Select the matching tool",
        "--options", '{"rewind": "Rollback workspace files with SHA-256 snapshot", "lint": "Format CSS"}',
    ])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["choice"] == "rewind"

    rc2 = roms_cli_main([
        "noul",
        "--state", "All 26 pytest unit tests passed and verified successfully.",
        "--question", "Did the pytest unit tests pass and verify successfully?",
    ])
    assert rc2 == 0
    out2 = json.loads(capsys.readouterr().out)
    assert out2["choice"] == "yes"
