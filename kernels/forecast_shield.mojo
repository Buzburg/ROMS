"""Mojo-cortex Kernel 4: Pre-Simulation Trajectory Forecaster & Loop Circuit Breaker."""

from std.collections import List
from std.math import sqrt

comptime STATE_DIM: Int = 128


@fieldwise_init
struct ShieldVerdict(Copyable, Movable):
    var goal_alignment: Float32
    var loop_similarity: Float32
    var hazard_score: Float32
    var p_success: Float32
    var blocked: Bool


def evaluate_shield_kernel(
    candidate_vec: List[Float32],
    goal_vec: List[Float32],
    prev_action_vec: List[Float32],
    hazard_score: Float32,
    min_p_success: Float32 = 0.45
) -> ShieldVerdict:
    """Computes goal alignment, cyclic repetition similarity, and pre-execution safety verdict."""
    var dot_goal = Float32(0.0)
    var dot_prev = Float32(0.0)
    var norm_cand = Float32(0.0)
    var norm_goal = Float32(0.0)
    var norm_prev = Float32(0.0)

    for i in range(STATE_DIM):
        var c = candidate_vec[i]
        var g = goal_vec[i]
        var p = prev_action_vec[i]
        dot_goal += c * g
        dot_prev += c * p
        norm_cand += c * c
        norm_goal += g * g
        norm_prev += p * p

    var nc = sqrt(norm_cand)
    var ng = sqrt(norm_goal)
    var np = sqrt(norm_prev)

    var align = Float32(0.5)
    if nc > 1e-8 and ng > 1e-8:
        align = ((dot_goal / (nc * ng)) + Float32(1.0)) * Float32(0.5)

    var loop_sim = Float32(0.0)
    if nc > 1e-8 and np > 1e-8:
        loop_sim = dot_prev / (nc * np)
        if loop_sim < 0.0:
            loop_sim = 0.0

    var p_success = (
        Float32(0.55) * align
        + Float32(0.25) * (Float32(1.0) - loop_sim)
        + Float32(0.20) * (Float32(1.0) - hazard_score)
    )

    var blocked = (
        (hazard_score > 0.70)
        or (loop_sim > 0.94)
        or (p_success < min_p_success)
    )

    return ShieldVerdict(align, loop_sim, hazard_score, p_success, blocked)


def main():
    print("mojo-cortex Kernel 4 (Pre-Simulation Forecaster & Loop Breaker) initialized.")
