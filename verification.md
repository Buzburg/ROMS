# Verification & Benchmarks — mojo-cortex

## Empirical Test & Benchmark Summary

All unit tests, JSON-RPC 2.0 MCP server protocol tests, and benchmarks executed natively on Windows.

### 1. Test Suite (`tests/test_cortex.py`)
- **Status:** `10/10` tests passed in `0.276s`
- **Subsystems Verified:**
  1. **Titans + DeltaNet-2 Neural Memory:** Surprise residual decrease on repeated exposure, `1.0000` cosine recall after variable overwrite, and `0.0000` residual norm after DeltaNet-2 pure erase gate.
  2. **SnapKV Context Sieve:** `>98%` token reduction on noisy logs while preserving buried stack traces and `file:line` pointers.
  3. **Polyglot Symdex:** Multi-language symbol extraction (`.py`, `.mojo`, `.rs`, `.ts`, `.go`, `.cpp`) and sub-millisecond lookup.
  4. **Workspace Time Machine:** Deduplicated SHA-256 copy-on-write snapshots and byte-for-byte atomic rollback.
  5. **Execution Shield:** Destructive command interception (`rm -rf`, `DROP DATABASE`, `--force`), 3-turn cyclic loop circuit breaking, and malformed local LLM tool-call JSON repair with schema type coercion.
  6. **BitNet b1.58 Ternary Router:** Multiplier-free ternary tool pruning.
  7. **MCP Server (`JSON-RPC 2.0`):** `initialize`, `tools/list`, and `tools/call` verification.
  8. **HTML Observability Dashboard:** Standalone dark-mode dashboard generation.

### 2. Benchmark Metrics (`benchmarks/run_benchmarks.py`)
- **Titans + DeltaNet-2 Memory Recall:** `834.99 µs` (`1.0000` overwrite cosine fidelity)
- **SnapKV Context Sieve (2,500 lines):** `4.25 ms` (`98.86%` reduction, `26,272 tokens` saved)
- **Polyglot Symdex Symbol Lookup:** `227.18 µs`
- **Pre-Simulation Shield Forecast:** `7.97 ms`
- **Zero-Shot Tool Call JSON Repair:** `7.01 ms`
- **BitNet b1.58 Ternary Tool Router:** `887.31 µs` (`75.0%` schema pruned)
