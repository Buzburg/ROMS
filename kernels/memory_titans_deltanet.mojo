"""
mojo-cortex Kernel 1: Hybrid Titans + Gated DeltaNet-2 Neural Memory
Combines Google's "Titans: Learning to Memorize at Test Time" (arXiv:2501.00663)
with "Gated DeltaNet-2: Decoupling Erase and Write in Linear Attention" (arXiv:2605.22791).
"""

from std.collections import List
from std.math import sqrt

comptime HEAD_DIM: Int = 64
comptime MATRIX_SIZE: Int = HEAD_DIM * HEAD_DIM  # 4096 float32 weights (16 KB in L1 cache)


@fieldwise_init
struct CortexMemoryState(Copyable, Movable):
    var weights: List[Float32]      # Primary associative state matrix M_t (64 x 64)
    var momentum: List[Float32]     # Titans surprise momentum buffer S_t (64 x 64)
    var updates: Int


@fieldwise_init
struct MemoryStepResult(Copyable, Movable):
    var surprise_score: Float32     # Pre-update prediction residual 0.5 * ||M_{t-1} k - v||^2
    var post_cosine: Float32        # Post-update recall fidelity cos(M_t k, v)
    var frobenius_norm: Float32     # ||M_t||_F


def create_cortex_memory() -> CortexMemoryState:
    var w = List[Float32](length=MATRIX_SIZE, fill=0.0)
    var m = List[Float32](length=MATRIX_SIZE, fill=0.0)
    return CortexMemoryState(w^, m^, 0)


def recall_vector(state: CortexMemoryState, key: List[Float32]) -> List[Float32]:
    """Computes associative recall y = M_t * k in O(d^2)."""
    var out = List[Float32](capacity=HEAD_DIM)
    for r in range(HEAD_DIM):
        var acc = Float32(0.0)
        var offset = r * HEAD_DIM
        for c in range(HEAD_DIM):
            acc += state.weights[offset + c] * key[c]
        out.append(acc)
    return out^


def fused_titans_deltanet_step(
    mut state: CortexMemoryState,
    key: List[Float32],
    value: List[Float32],
    alpha_erase: Float32 = 1.0,
    beta_write: Float32 = 1.0,
    eta_momentum: Float32 = 0.25,
    gamma_decay: Float32 = 0.999
) -> MemoryStepResult:
    """
    Executes the hybrid Gated DeltaNet-2 + Titans memory update:
      1. Recall existing projection: v_old = M_{t-1} * k_t
      2. Compute surprise residual:  e_t = v_old - v_t
      3. Compute DeltaNet-2 target:  delta_v = beta_write * v_t - (gamma_decay * alpha_erase) * v_old
      4. Update surprise momentum:   S_t = eta * S_{t-1} + delta_v * k_t^T
      5. Apply state update:         M_t = gamma_decay * M_{t-1} + delta_v * k_t^T + (1 - alpha_erase) * S_t
    """
    var v_old = recall_vector(state, key)
    var surprise = Float32(0.0)
    for i in range(HEAD_DIM):
        var diff = v_old[i] - value[i]
        surprise += Float32(0.5) * diff * diff

    var norm_sq = Float32(0.0)
    var mom_blend = Float32(1.0) - alpha_erase

    for r in range(HEAD_DIM):
        var offset = r * HEAD_DIM
        var delta_r = (beta_write * value[r]) - (gamma_decay * alpha_erase * v_old[r])
        for c in range(HEAD_DIM):
            var idx = offset + c
            var rank1_update = delta_r * key[c]
            var s_new = (eta_momentum * state.momentum[idx]) + rank1_update
            var w_new = (gamma_decay * state.weights[idx]) + rank1_update + (mom_blend * s_new)
            state.momentum[idx] = s_new
            state.weights[idx] = w_new
            norm_sq += w_new * w_new

    state.updates += 1

    # Compute post-update cosine alignment
    var v_post = recall_vector(state, key)
    var dot = Float32(0.0)
    var na = Float32(0.0)
    var nb = Float32(0.0)
    for i in range(HEAD_DIM):
        dot += v_post[i] * value[i]
        na += v_post[i] * v_post[i]
        nb += value[i] * value[i]

    var post_cos = Float32(0.0)
    var denom = sqrt(na) * sqrt(nb)
    if denom > 1e-8:
        post_cos = dot / denom

    return MemoryStepResult(surprise, post_cos, sqrt(norm_sq))


def main():
    print("mojo-cortex Kernel 1 (Titans + Gated DeltaNet-2) initialized.")
