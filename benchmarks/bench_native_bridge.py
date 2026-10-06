"""Deterministic parity checks and paired timings across the real Python/Mojo 1.1.0 boundary."""

import os
import sys
import json
import time
import random
import platform
import statistics

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from cortex.runtime import select_context, prompt_lookup


def median_ms(fn) -> float:
    samples = []
    for _ in range(9):
        start = time.perf_counter_ns()
        fn()
        samples.append((time.perf_counter_ns() - start) / 1e6)
    return statistics.median(samples)


def run(native_pack, native_lookup) -> None:
    rng = random.Random(20261006)

    # 1. Verify 400 random 0/1 Knapsack Context Packing parity cases
    for _ in range(400):
        count = rng.randrange(0, 21)
        costs = [rng.randrange(1, 900) for _ in range(count)]
        values = [rng.randrange(1, 10000) for _ in range(count)]
        budget = rng.randrange(0, 3000)
        required = rng.randrange(-1, count) if count else -1
        if required >= 0 and costs[required] > budget:
            required = -1
        assert list(native_pack(costs, values, budget, required)) == select_context(costs, values, budget, required)

    # 2. Verify 200 random Prompt Lookup speculative drafting parity cases
    for _ in range(200):
        length = rng.randrange(2, 128)
        hist = [rng.randrange(1, 16) for _ in range(length)]
        win = rng.randrange(1, 5)
        lim = rng.randrange(1, 8)
        assert list(native_lookup(hist, win, lim)) == prompt_lookup(hist, win, lim)

    # 3. Verify invalid boundary inputs are rejected by native Mojo
    for costs, values, budget, required in [
        ([0], [1], 20, -1),
        ([1], [], 20, -1),
        ([1] * 65, [1] * 65, 20, -1),
        ([1], [1], 20001, -1),
        ([10], [1], 5, 0),
    ]:
        try:
            native_pack(costs, values, budget, required)
        except Exception:
            pass
        else:
            raise AssertionError("Native invalid input accepted")

    # 4. Measure paired Python vs Mojo 1.1.0 timings
    cases = []
    for label, costs, budget in [
        ("tight-20", [400 + i * 41 for i in range(20)], 2000),
        ("standard-20", [500 + i * 73 for i in range(20)], 6000),
        ("large-20", [1400 + i * 79 for i in range(20)], 18000),
    ]:
        values = [10000 // (i + 1) for i in range(len(costs))]
        required = len(costs) - 1
        expected = select_context(costs, values, budget, required)
        assert list(native_pack(costs, values, budget, required)) == expected
        py_ms = median_ms(lambda: select_context(costs, values, budget, required))
        mojo_ms = median_ms(lambda: native_pack(costs, values, budget, required))
        cases.append({
            "case": label,
            "records": len(costs),
            "budget_chars": budget,
            "python_ms": round(py_ms, 6),
            "mojo_ms": round(mojo_ms, 6),
            "speedup_x": round(py_ms / max(1e-9, mojo_ms), 2),
            "selected": len(expected),
        })

    # 5. Measure paired Python vs Mojo 1.1.0 Prompt Lookup speculative drafting timing
    hist_512 = [(i * 7 + (i // 16)) % 32 for i in range(512)] + [1, 2, 3, 4]
    hist_512[120:128] = [1, 2, 3, 4, 99, 100, 101, 102]
    assert list(native_lookup(hist_512, 4, 4)) == prompt_lookup(hist_512, 4, 4)
    py_lookup_ms = median_ms(lambda: prompt_lookup(hist_512, 4, 4))
    mojo_lookup_ms = median_ms(lambda: native_lookup(hist_512, 4, 4))

    payload = {
        "python": platform.python_version(),
        "machine": platform.machine(),
        "knapsack_parity_cases": 400,
        "prompt_lookup_parity_cases": 200,
        "invalid_inputs_rejected": 5,
        "samples": 9,
        "cases": cases,
        "prompt_lookup_512": {
            "python_ms": round(py_lookup_ms, 6),
            "mojo_ms": round(mojo_lookup_ms, 6),
            "speedup_x": round(py_lookup_ms / max(1e-9, mojo_lookup_ms), 2),
            "drafted_tokens": list(native_lookup(hist_512, 4, 4)),
        },
    }
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "native_benchmark_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(json.dumps(payload, indent=2), flush=True)

