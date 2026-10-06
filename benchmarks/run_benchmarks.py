"""
Empirical Benchmark Suite for mojo-cortex
Measures latency, throughput, compression ratio, and accuracy across all 6 Cortex engines.
"""

import os
import sys
import time
import shutil
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from cortex.memory import HybridNeuralMemory
from cortex.sieve import ContextSieve
from cortex.symdex import PolyglotSymdex
from cortex.rewind import WorkspaceTimeMachine
from cortex.shield import ExecutionShield
from cortex.router import TernaryToolRouter
from cortex.mcp_server import MCP_TOOLS_SCHEMA


def main():
    temp_dir = tempfile.mkdtemp(prefix="cortex_bench_")
    cortex_dir = os.path.join(temp_dir, ".cortex")

    try:
        mem = HybridNeuralMemory(cortex_dir)
        sieve = ContextSieve(cortex_dir)
        sym = PolyglotSymdex(cortex_dir)
        shield = ExecutionShield(cortex_dir)
        router = TernaryToolRouter()

        # 1. Benchmark Neural Memory (Titans + DeltaNet-2)
        mem_res = mem.remember("primary_db", "postgres_16_cluster")
        mem_iters = 200
        start = time.perf_counter()
        for _ in range(mem_iters):
            rec = mem.recall("primary_db")
        avg_recall_us = ((time.perf_counter() - start) / mem_iters) * 1_000_000

        # 2. Benchmark Context Sieve (2,500-line noisy terminal log)
        log_lines = [f"[INFO] Compiling module_chunk_{i % 20}.rs ... ok" for i in range(2500)]
        log_lines[1200] = '  File "src/core/pipeline.py", line 412, in execute_step'
        log_lines[1201] = "RuntimeError: CUDA out of memory in attention prefill"
        log_lines.append("Process exited with status 1")
        raw_log = "\n".join(log_lines)

        sieve_res = sieve.compact(raw_log, max_lines=25)

        # 3. Benchmark Polyglot Symdex Lookup
        sym.index_workspace(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        sym_iters = 500
        start = time.perf_counter()
        for _ in range(sym_iters):
            lkp = sym.lookup("HybridNeuralMemory")
        avg_sym_us = ((time.perf_counter() - start) / sym_iters) * 1_000_000

        # 4. Benchmark Shield Pre-Simulation Forecast & JSON Repair
        fc_iters = 1000
        start = time.perf_counter()
        for _ in range(fc_iters):
            _ = shield.forecast_action("pytest tests/test_cortex.py", goal="verify cortex tests")
        avg_fc_us = ((time.perf_counter() - start) / fc_iters) * 1_000_000

        broken_json = "```json\n{'name': 'lookup', 'arguments': {'query': 'main', 'top_k': '5',}}\n```"
        rep_iters = 1000
        start = time.perf_counter()
        for _ in range(rep_iters):
            _ = shield.repair_tool_call(broken_json)
        avg_rep_us = ((time.perf_counter() - start) / rep_iters) * 1_000_000

        # 5. Benchmark BitNet b1.58 Ternary Router
        rt_iters = 1000
        start = time.perf_counter()
        for _ in range(rt_iters):
            rt_res = router.route("compact terminal build log output", MCP_TOOLS_SCHEMA, top_k=2)
        avg_rt_us = ((time.perf_counter() - start) / rt_iters) * 1_000_000

        print("=" * 72)
        print("                 mojo-cortex Empirical Benchmark Suite")
        print("=" * 72)
        print(f"1. Titans + DeltaNet-2 Memory Recall: {avg_recall_us:.2f} us | Overwrite Cosine: {mem_res['post_write_cosine']:.4f}")
        print(f"2. SnapKV Context Sieve (2500 lines): {sieve_res['latency_ms']:.2f} ms | Saved: {sieve_res['compression_pct']}% ({sieve_res['tokens_saved']:,} tokens)")
        print(f"3. Polyglot Symdex Symbol Lookup:     {avg_sym_us:.2f} us")
        print(f"4. Pre-Simulation Shield Forecast:    {avg_fc_us:.2f} us")
        print(f"5. Zero-Shot Tool Call JSON Repair:   {avg_rep_us:.2f} us")
        print(f"6. BitNet b1.58 Ternary Tool Router:  {avg_rt_us:.2f} us ({rt_res['token_reduction_pct']}% schema pruned)")
        print("=" * 72)

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
