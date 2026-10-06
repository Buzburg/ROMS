"""Mojo-cortex Kernel 3: SnapKV Observation-Window Clustering & Log Sieve."""

from std.collections import List
from std.math import sqrt

comptime EMBED_DIM: Int = 64


def snapkv_score_positions(
    key_states: List[Float32],
    num_tokens: Int,
    obs_window_size: Int = 8,
    pool_kernel: Int = 3
) -> List[Float32]:
    """Computes SnapKV importance scores for each prompt position with 1D max-pooling."""
    var raw_scores = List[Float32](length=num_tokens, fill=0.0)
    var obs_start = num_tokens - obs_window_size
    if obs_start < 0:
        obs_start = 0

    # Score prefix positions by dot-product similarity with observation window queries
    for pos in range(obs_start):
        var pos_offset = pos * EMBED_DIM
        var score_acc = Float32(0.0)
        for obs in range(obs_start, num_tokens):
            var obs_offset = obs * EMBED_DIM
            var dot = Float32(0.0)
            for d in range(EMBED_DIM):
                dot += key_states[pos_offset + d] * key_states[obs_offset + d]
            score_acc += dot
        raw_scores[pos] = score_acc / Float32(num_tokens - obs_start)

    # Observation window tokens always receive maximal retention score
    for obs in range(obs_start, num_tokens):
        raw_scores[obs] = 1e6

    # 1D Max-Pooling to preserve contiguous semantic chunks (SnapKV clustering)
    var pooled = List[Float32](capacity=num_tokens)
    var half_k = pool_kernel // 2
    for i in range(num_tokens):
        var max_v = raw_scores[i]
        for offset in range(-half_k, half_k + 1):
            var neighbor = i + offset
            if neighbor >= 0 and neighbor < num_tokens:
                if raw_scores[neighbor] > max_v:
                    max_v = raw_scores[neighbor]
        pooled.append(max_v)

    return pooled^


def main():
    print("mojo-cortex Kernel 3 (SnapKV Observation-Window Sieve) initialized.")
