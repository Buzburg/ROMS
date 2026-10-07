"""
ROMS numerical decision kernels (not connected to the Python decision runtime).
Source implementations of:
  1. Temperature-scaled softmax decision head (`decide`) with dual abstention gates
     (confidence < threshold or margin < min_margin) and Shannon concentration.
  2. Caller-supplied vector dot-product ranking (`rank_options`).
  3. A recurrent matrix update (`wkv7_state_step`, a legacy function name).

These kernels contain no trained model weights. Their presence does not establish
native execution, calibrated factual confidence, or measured latency in Python.
"""

from std.collections import List
from std.math import exp, log, isfinite


@fieldwise_init
struct Decision(Copyable, Movable):
    var index: Int
    var probabilities: List[Float64]
    var confidence: Float64
    var margin: Float64
    var concentration: Float64
    var expected_score: Float64
    var abstain: Bool


def decide(
    logits: List[Float64],
    allowed: List[Bool],
    temperature: Float64 = 1.0,
    threshold: Float64 = 0.8,
    min_margin: Float64 = 0.1
) raises -> Decision:
    """Normalize caller-supplied logits and apply confidence/margin cutoffs."""
    if len(logits) < 2 or len(logits) != len(allowed):
        raise Error("decision needs matching logits and mask, at least two options")
    if (
        not isfinite(temperature)
        or temperature <= 0.0
        or not isfinite(threshold)
        or threshold < 0.0
        or threshold > 1.0
        or not isfinite(min_margin)
        or min_margin < 0.0
        or min_margin > 1.0
    ):
        raise Error("invalid decision calibration or abstention settings")

    var best = -1
    var permitted_count = 0
    for i in range(len(logits)):
        if not isfinite(logits[i]):
            raise Error("non-finite decision logit")
        if allowed[i]:
            permitted_count += 1
            if best == -1 or logits[i] > logits[best]:
                best = i

    if best == -1 or permitted_count < 2:
        raise Error("at least two permitted decision options are required")

    var probabilities = List[Float64](capacity=len(logits))
    var total = Float64(0.0)
    for i in range(len(logits)):
        var p = Float64(0.0)
        if allowed[i]:
            p = exp((logits[i] - logits[best]) / temperature)
        probabilities.append(p)
        total += p

    var second = Float64(0.0)
    var expected = Float64(0.0)
    var entropy = Float64(0.0)
    for i in range(len(logits)):
        probabilities[i] /= total
        var p_i = probabilities[i]
        expected += Float64(i) * p_i
        if p_i > 1e-15:
            entropy -= p_i * log(p_i)
        if i != best and p_i > second:
            second = p_i

    var confidence = probabilities[best]
    var margin = confidence - second
    var max_entropy = log(Float64(permitted_count))
    var concentration = Float64(0.0)
    if max_entropy > 1e-12:
        concentration = 1.0 - (entropy / max_entropy)
        if concentration < 0.0:
            concentration = 0.0
        elif concentration > 1.0:
            concentration = 1.0

    var should_abstain = (confidence < threshold) or (margin < min_margin)
    return Decision(
        best,
        probabilities^,
        confidence,
        margin,
        concentration,
        expected,
        should_abstain
    )


def rank_options(
    context: List[Float64],
    options: List[List[Float64]]
) raises -> List[Float64]:
    """Dot-product ranking for caller-supplied vectors."""
    if len(context) == 0 or len(options) < 2:
        raise Error("empty embeddings or insufficient options")
    var scores = List[Float64](capacity=len(options))
    for option in options:
        if len(option) != len(context):
            raise Error("embedding dimension mismatch")
        var score = Float64(0.0)
        for i in range(len(context)):
            if not isfinite(context[i]) or not isfinite(option[i]):
                raise Error("non-finite embedding")
            score += context[i] * option[i]
        if not isfinite(score):
            raise Error("embedding score overflow")
        scores.append(score)
    return scores^


def wkv7_state_step(
    mut state: List[Float64],
    decay: List[Float64],
    key: List[Float64],
    value: List[Float64],
    iclr: List[Float64],
    dim: Int
):
    """
    Recurrent matrix update; this function alone does not implement a language model:
    S_t = S_{t-1} * diag(w_t) - (S_{t-1} @ k_t) * (a_t * k_t)^T + v_t @ k_t^T
    Storage depends on dim. This source has no runtime binding or performance claim.
    """
    for i in range(dim):
        var s_dot_k = Float64(0.0)
        var row_offset = i * dim
        for j in range(dim):
            s_dot_k += state[row_offset + j] * key[j]
        var v_i = value[i]
        for j in range(dim):
            var idx = row_offset + j
            var decayed = state[idx] * decay[j]
            var delta_removal = s_dot_k * iclr[j] * key[j]
            var hebbian_write = v_i * key[j]
            state[idx] = decayed - delta_removal + hebbian_write
