"""Native Mojo 1.1.0 verification suite for all five cortex kernel modules."""

from std.collections import List
from std.testing import assert_equal, assert_true
from memory_titans_deltanet import (
    HEAD_DIM,
    create_cortex_memory,
    fused_titans_deltanet_step,
    recall_vector,
)
from ternary_router import (
    ROUTER_DIM,
    TernaryToolSignature,
    score_tool_multiplier_free,
)
from sieve_snapkv import EMBED_DIM, snapkv_score_positions
from forecast_shield import STATE_DIM, evaluate_shield_kernel
from runtime_mojond_roms import (
    PrefixIndex,
    prompt_lookup,
    kv_bytes,
    TokenBudget,
    select_context,
    binarize_embedding,
)


def main() raises:
    # 1. Verify Hybrid Titans + Gated DeltaNet-2 Memory Kernel
    var mem = create_cortex_memory()
    var k1 = List[Float32](length=HEAD_DIM, fill=0.0)
    k1[0] = 1.0  # Unit basis key 0
    var v1 = List[Float32](length=HEAD_DIM, fill=0.0)
    v1[2] = 1.0
    var v2 = List[Float32](length=HEAD_DIM, fill=0.0)
    v2[5] = 1.0

    var res1 = fused_titans_deltanet_step(mem, k1, v1, 1.0, 1.0, 0.25, 1.0)
    assert_true(res1.surprise_score > 0.49)
    assert_true(res1.post_cosine > 0.999)

    # Overwrite k1 with v2 -> exact 1.0000 recall via DeltaNet-2 erase gate
    var res2 = fused_titans_deltanet_step(mem, k1, v2, 1.0, 1.0, 0.25, 1.0)
    assert_true(res2.post_cosine > 0.999)
    var recalled = recall_vector(mem, k1)
    assert_true(recalled[5] > 0.999)

    # Pure erase gate (alpha=1, beta=0)
    var zero_v = List[Float32](length=HEAD_DIM, fill=0.0)
    _ = fused_titans_deltanet_step(mem, k1, zero_v, 1.0, 0.0, 0.0, 1.0)
    var erased_vec = recall_vector(mem, k1)
    assert_true(erased_vec[5] < 1e-5 and erased_vec[5] > -1e-5)

    # 2. Verify BitNet b1.58 Multiplier-Free Ternary Tool Router
    # Pack +1 (code 2 -> 0b10101010 = 170) into all 32 bytes
    var packed = List[UInt8](length=ROUTER_DIM // 4, fill=UInt8(170))
    var sig = TernaryToolSignature(1, packed^, Float32(0.5))
    var q_int8 = List[Int](length=ROUTER_DIM, fill=2)
    var router_score = score_tool_multiplier_free(sig, q_int8)
    # 128 * 2 * 0.5 = 128.0
    assert_true(router_score > 127.9 and router_score < 128.1)

    # 3. Verify SnapKV Observation-Window Clustering Kernel
    var keys = List[Float32](length=16 * EMBED_DIM, fill=0.1)
    var snap_scores = snapkv_score_positions(keys, 16, 4, 3)
    assert_equal(len(snap_scores), 16)
    assert_true(snap_scores[15] >= 1e5)

    # 4. Verify Pre-Simulation Forecaster & Loop Circuit Breaker
    var cand = List[Float32](length=STATE_DIM, fill=0.5)
    var goal = List[Float32](length=STATE_DIM, fill=0.5)
    var prev = List[Float32](length=STATE_DIM, fill=0.5)
    var verdict_loop = evaluate_shield_kernel(cand, goal, prev, 0.0, 0.45)
    assert_equal(verdict_loop.blocked, True)

    var prev_diff = List[Float32](length=STATE_DIM, fill=0.0)
    prev_diff[0] = 1.0
    var verdict_ok = evaluate_shield_kernel(cand, goal, prev_diff, 0.0, 0.45)
    assert_equal(verdict_ok.blocked, False)

    # 5. Verify mojond PrefixIndex, prompt_lookup, kv_bytes, and TokenBudget
    var index = PrefixIndex()
    index.insert([1, 2, 3, 4], 4, 0)
    index.insert([1, 2, 8, 9], 4, 1)
    var hit = index.match([1, 2, 3, 7])
    assert_equal(hit[0], 0)
    assert_equal(hit[1], 3)

    var draft = prompt_lookup([4, 5, 6, 7, 4, 5], 2, 2)
    assert_equal(len(draft), 2)
    assert_equal(draft[0], 6)
    assert_equal(draft[1], 7)
    assert_equal(kv_bytes(36, 8, 128, 16, 2), 2359296)

    var budget = TokenBudget(100)
    budget.acquire(70)
    assert_equal(budget.available(31), False)
    budget.release(70)
    assert_equal(budget.available(100), True)

    # 6. Verify ROMS 0/1 Knapsack Warning-Preserving Context Selector & BinaryVector
    var picked = select_context([400, 500, 300], [1000, 900, 200], 750, 2)
    assert_equal(len(picked), 2)
    assert_equal(picked[0], 0)
    assert_equal(picked[1], 2)  # Required failed-attempt warning index 2 preserved

    var emb_a = List[Float32](length=384, fill=1.0)
    var emb_b = List[Float32](length=384, fill=1.0)
    var bin_a = binarize_embedding(emb_a)
    var bin_b = binarize_embedding(emb_b)
    assert_equal(bin_a.hamming_distance(bin_b), 0)
    assert_true(bin_a.similarity(bin_b) > 0.999)

    print("PASS: All 6 native Mojo 1.1.0 kernel suites verified (Titans+DeltaNet2, BitNet, SnapKV, Shield, mojond, ROMS)")
