"""Regression checks for advisory grounding, input bounds, and state privacy."""
import builtins
import math

import pytest

from app.decisions import (
    BERTopicDiscoveryEngine,
    GooseStateDecisionHead,
    HashedStateHead,
    ROMSDecisionEngine,
    TopicDiscoveryEngine,
    decide,
    distribution_from_logprobs,
    encode_hashed_vector,
    rank_options,
    validate_question,
)


@pytest.mark.parametrize(("evidence", "question", "reason"), [
    ("", "Did the safety tests pass?", "evidence_missing"),
    ("The lunch menu is tomato soup.", "Did the safety tests pass?", "evidence_not_relevant"),
    ("The safety tests did not pass.", "Did the safety tests pass?", "ambiguous_negation"),
    ("The safety tests passed.", "Did the safety tests not pass?", "ambiguous_negation"),
    ("The safety tests didn't pass.", "Did the safety tests pass?", "ambiguous_negation"),
    ("The safety tests failed.", "Did the safety tests pass?", "ambiguous_negation"),
    ("The safety tests may pass.", "Did the safety tests pass?", "uncertain_or_pending"),
    ("The safety tests pass requirement is pending.", "Did the safety tests pass?", "uncertain_or_pending"),
    ("The safety tests should pass.", "Did the safety tests pass?", "uncertain_or_pending"),
    ("The safety tests are expected to pass.", "Did the safety tests pass?", "uncertain_or_pending"),
    ("If the safety tests pass, publish the result.", "Did the safety tests pass?", "uncertain_or_pending"),
    ("The safety tests passed.", "Could the safety tests pass?", "uncertain_or_pending"),
])
def test_unsupported_or_negated_verification_abstains(evidence, question, reason, tmp_path):
    result = ROMSDecisionEngine(state_dir=str(tmp_path / "unused"), persist_discovery=False).decide_noul(
        evidence, question, threshold=0.0, min_margin=0.0,
    )
    assert result["abstained"] is True
    assert reason in result["abstention_reasons"]
    assert result["probabilities"] == {"yes": 0.5, "no": 0.5}
    assert result["confidence"] == 0.5
    assert result["execution_allowed"] is False


def test_negation_remains_in_hashed_features():
    assert encode_hashed_vector("the tests passed") != encode_hashed_vector("the tests not passed")


def test_missing_or_irrelevant_state_never_accepts_a_route(tmp_path):
    engine = ROMSDecisionEngine(state_dir=str(tmp_path / "unused"), persist_discovery=False)
    for goal in ("", "tomato soup"):
        report = engine.route(goal, {"backup": "Backup database", "lint": "Format source code"})
        assert report["selected_route"] is None and report["accepted"] is False
        assert report["execution_allowed"] is False


def test_in_memory_discovery_never_creates_reads_or_writes_state(tmp_path, monkeypatch):
    directory = tmp_path / "state"
    directory.mkdir()
    state_file = directory / "bertopic_decisions.json"
    sentinel = b'{"private": "existing user state"}'
    state_file.write_bytes(sentinel)

    def forbidden(*args, **kwargs):
        raise AssertionError("in-memory decision attempted state I/O")

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", forbidden)
        patch.setattr("app.decisions.os.makedirs", forbidden)
        patch.setattr(TopicDiscoveryEngine, "_load", forbidden)
        engine = ROMSDecisionEngine(state_dir=str(directory), persist_discovery=False)
        result = engine.decide_noul("", "Did the tests pass?")
        assert result["abstained"]
        assert engine.discovery.summary()["total_documents"] == 1
        other = ROMSDecisionEngine(state_dir=str(directory / "missing"), persist_discovery=False)
        assert other.discovery.summary()["total_documents"] == 0
    assert state_file.read_bytes() == sentinel
    assert not (directory / "missing").exists()


def test_truthful_metadata_and_compatibility_aliases(tmp_path):
    assert BERTopicDiscoveryEngine is TopicDiscoveryEngine
    assert GooseStateDecisionHead is HashedStateHead
    engine = ROMSDecisionEngine(state_dir=str(tmp_path), persist_discovery=False)
    report = engine.ask("", [{"id": "q", "type": "noul", "question": "Did tests pass?"}])
    result = report["results"]["q"]
    for item in (report, result):
        assert item["engine"] == "ROMS Decision Maker"
        assert item["backend"] == "lexical_heuristic"
        assert item["probabilities_calibrated"] is False
        assert item["advisory_only"] is True
        assert item["execution_allowed"] is False
    assert report["state"] == report["goose_state"]
    assert report["state"]["model_state"] is False
    assert result["state_payload_bytes"] == result["goose_state_bytes"] == 4608
    assert result["topic_discovery"] == result["bertopic_open_set_discovery"]


def _meta(entries):
    return {"completion_tokens": 1, "finish_reason": {"type": "length"},
            "output_token_ids_logprobs": [entries]}


@pytest.mark.parametrize("entries", [
    [[-math.inf, 1], [-math.inf, 2]],
    [[math.nan, 1], [-1.0, 2]],
    [[math.inf, 1], [-1.0, 2]],
    [[0.1, 1], [-1.0, 2]],
    [[-10**1000, 1], [-1.0, 2]],
    [[-1.0, 1], [-2.0, 1]],
    [[-1.0, True], [-2.0, 2]],
    [[-1.0, 1]],
    [None, [-1.0, 2]],
    [[-1.0], [-2.0, 2]],
    [[-1.0, 1], [-2.0, 3]],
])
def test_malformed_or_zero_mass_logprobs_are_rejected(entries):
    with pytest.raises(ValueError):
        distribution_from_logprobs(_meta(entries), [1, 2])


@pytest.mark.parametrize("token_ids", [[], [1], [1, 1], [True, 2], [-1, 2], "12"])
def test_option_token_ids_are_validated(token_ids):
    with pytest.raises(ValueError):
        distribution_from_logprobs(_meta([[-1.0, 1], [-2.0, 2]]), token_ids)


def test_zero_probability_option_is_valid_if_another_has_mass():
    assert distribution_from_logprobs(_meta([[-math.inf, 1], [-2.0, 2]]), [1, 2]) == [0.0, 1.0]


@pytest.mark.parametrize("options", [[None, "yes"], [{"description": "first"}, "second"],
                                      [" ", "second"], {"x" * 65: "first", "b": "second"}])
def test_question_options_are_bounded_strings_without_coercion(options):
    with pytest.raises(ValueError):
        validate_question({"id": "q", "type": "choice", "question": "Which?", "options": options})


@pytest.mark.parametrize("temperature", [False, "0.3", math.nan, -1.0, 10**1000])
def test_invalid_settings_are_rejected_before_creating_state(temperature, tmp_path):
    directory = tmp_path / "not-created"
    with pytest.raises(ValueError):
        ROMSDecisionEngine(state_dir=str(directory), temperature=temperature)
    assert not directory.exists()


def test_invalid_override_is_rejected_before_scoring(tmp_path, monkeypatch):
    engine = ROMSDecisionEngine(state_dir=str(tmp_path), persist_discovery=False)
    monkeypatch.setattr(engine.state_head, "ingest_context", lambda text: pytest.fail("scoring invalid input"))
    with pytest.raises(ValueError):
        engine.decide_noul("tests passed", "Did tests pass?", threshold=True)


def test_nonfinite_state_and_truthy_mask_are_rejected(tmp_path):
    engine = ROMSDecisionEngine(state_dir=str(tmp_path), persist_discovery=False)
    with pytest.raises(ValueError):
        engine.decide_noul({"value": math.nan}, "Is this finite?")
    with pytest.raises(ValueError):
        decide([1.0, 0.0], allowed=["yes", "no"])


def test_direct_topic_input_is_bounded_before_mutation(tmp_path):
    discovery = TopicDiscoveryEngine(state_dir=str(tmp_path), persist=False)
    for text in ("", "x" * 20_001, None):
        with pytest.raises(ValueError):
            discovery.add_document(text)
    assert discovery.summary()["total_documents"] == 0


@pytest.mark.parametrize(("context", "options"), [
    ([1.0], None), ([1.0], [None, [0.0]]), ([True], [[1.0], [0.0]]),
])
def test_invalid_vector_inputs_raise_value_error(context, options):
    with pytest.raises(ValueError):
        rank_options(context, options)


def test_explicit_legacy_persistence_still_roundtrips(tmp_path):
    engine = ROMSDecisionEngine(state_dir=str(tmp_path), persist_discovery=True)
    engine.decide_noul("", "Did tests pass?")
    assert (tmp_path / "bertopic_decisions.json").is_file()
    restored = ROMSDecisionEngine(state_dir=str(tmp_path), persist_discovery=True)
    assert restored.discovery.summary()["total_documents"] == 1


def test_extreme_finite_integer_logits_normalize_without_overflow():
    result = decide([-10**308, 10**308])
    assert result.probabilities == [0.0, 1.0]
    assert result.index == 1


def test_finite_integer_products_that_overflow_raise_value_error():
    with pytest.raises(ValueError, match="Embedding score overflow"):
        rank_options([10**200], [[10**200], [1]])
