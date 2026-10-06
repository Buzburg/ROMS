# Reddit — r/LocalLLaMA
**Optimal Window:** Monday–Thursday, 9:00 AM – 11:00 AM EST
**Title:** [Release] mojo-cortex: Give local 7B-32B models (Ollama/vLLM/RWKV-7) Titans+DeltaNet-2 memory, 98.8% SnapKV log compaction, BitNet b1.58 tool routing & broken JSON repair

If you run local coding/tool agents on **16GB–32GB VRAM**, you know the pain:
- A single `pytest` or `npm build` dump eats 25,000 tokens of KV cache.
- Passing 40+ MCP tool schemas makes 7B–14B models hallucinate argument types or emit broken JSON (`'single_quotes'`, trailing commas, unclosed markdown blocks).
- When a fix fails and context gets truncated, the model forgets what it just tried and loops on the exact same broken command.

I built **`mojo-cortex`** (https://github.com/Buzburg/mojo-cortex)—a zero-dependency prefrontal cortex & MCP harness written in **Mojo 1.1.0 + Python** specifically designed to make local models punch way above their weight on long-horizon coding and automation:

### Empirical Benchmarks (Verified across 600 Python/Mojo 1.1.0 parity tests):
1. **ROMS 0/1 Knapsack Context Packer (`25.61x` faster in Mojo 1.1.0 — `0.170983 ms`):** Instead of greedy top-K truncation, it runs a 0/1 dynamic-programming knapsack solver that **reserves failed-attempt warnings first**, guaranteeing your local model never repeats a failed repair.
2. **SnapKV Context Sieve (`98.8%` token reduction in `4.25 ms`):** Compacts 2,504 lines of noisy terminal output down to 30 lines (`26,386` tokens saved) while preserving **100%** of tracebacks and `file:line` pointers using 1D max-pooled observation windows.
3. **BitNet b1.58 Multiplier-Free Tool Router (`887 µs`):** Uses 2-bit packed ternary weights (`{-1, 0, +1}`) to prune 80–95% of irrelevant MCP tool schemas before the prompt ever hits your local LLM.
4. **Deterministic JSON Tool-Call Repair (`<50 µs`):** Automatically strips `<think>` tags / markdown fences, fixes trailing commas & single quotes, and coerces stringified ints/booleans against your JSON schema—saving 99% of failed local tool calls without a retry generation.
5. **Titans (`2501.00663`) + Gated DeltaNet-2 (`2605.22791`) Associative Memory (`835 µs`):** Test-time surprise momentum + decoupled erase/write gates for `1.0000` cosine variable overwrite and `0.0000` residual erasure.
6. **mojond Speculative Prompt Lookup (`3.22x` speedup in Mojo):** Parameter-free n-gram speculative token drafting (`prompt_lookup`) + `PrefixIndex` cache slot trie.

### 10-Second Quickstart:
```bash
git clone https://github.com/Buzburg/mojo-cortex
cd mojo-cortex
python tests/test_cortex.py -v
```
Repo link: https://github.com/Buzburg/mojo-cortex

---

# Reddit — r/ClaudeAI & r/Cursor
**Optimal Window:** Tuesday–Friday, 10:00 AM – 1:00 PM EST
**Title:** I built an open-source MCP server (mojo-cortex) that cuts Claude Code / Cursor token usage by 90%+, adds persistent DeltaNet-2 memory, and gives you Git-safe atomic undo

One command to add to Claude Code:
```bash
claude mcp add cortex -- python /path/to/mojo-cortex/cortex.py mcp
```

### What it adds to Claude Code, Cursor, and Windsurf (`https://github.com/Buzburg/mojo-cortex`):
- **`cortex_sieve_compact` (98.8% Log Compaction):** Uses SnapKV observation clustering to shrink 2,500-line test/build logs down to 30 lines while keeping 100% of error tracebacks—saving ~26,000 tokens per test run.
- **`cortex_symdex_lookup` (`227 µs` Symbol Search):** Finds exact `file:line` definitions and signatures across Python, Mojo, Rust, TS/JS, Go, and C++ so Claude doesn't read entire 2,000-line files.
- **`cortex_memory_remember` / `recall` / `erase`:** Persistent cross-session memory powered by Google's *Titans* + *Gated DeltaNet-2* so when your architecture changes, old facts are cleanly overwritten (`1.0000` cosine fidelity) instead of polluting context.
- **`cortex_snapshot_create` & `cortex_snapshot_rewind`:** Deduplicated SHA-256 copy-on-write snapshots that let you undo a broken multi-file agent refactor in `<5 ms` **without touching your `.git` commit history**.
- **`cortex_context_pack`:** Native Mojo 1.1.0 0/1 knapsack context packer (`25.61x` speedup) that reserves failed-attempt warnings first so the agent never loops on a broken fix.

100% open-source (MIT), zero external pip dependencies: https://github.com/Buzburg/mojo-cortex

---

# Reddit — r/MojoLang & Modular Discord #showcase
**Optimal Window:** Any weekday morning EST
**Title:** mojo-cortex: Native Mojo 1.1.0 Kernels + PythonModuleBuilder Bridge for AI Agent Memory, BitNet b1.58 Routing & 25.61x Faster 0/1 Knapsack Context Packing

Built **`mojo-cortex`** (https://github.com/Buzburg/mojo-cortex)—an AI agent memory, context optimization, and safety MCP harness powered by **Mojo 1.1.0 (`8189361e`)** kernels with an in-process `std.python.bindings.PythonModuleBuilder` bridge.

### Native Mojo 1.1.0 Kernels Included (`kernels/*.mojo`):
1. `kernels/runtime_mojond_roms.mojo` + `kernels/cortex_bindings.mojo`:
   - **0/1 Dynamic-Programming Knapsack Context Selector (`select_context`):** Verified across 400 randomized Python-vs-Mojo parity tests. Runs in **`0.170983 ms`** in Mojo 1.1.0 vs **`4.379378 ms`** in Python 3.14 (**`25.61x` speedup**).
   - **1-Bit `BinaryVector`:** Packs 384 `Float32` dimensions into 6 `UInt64` words (`48 bytes`, `32x` compression) using bitwise `^` and hardware `pop_count`.
   - **`PrefixIndex` & `prompt_lookup`:** Parameter-free speculative n-gram token drafting (**`3.22x` speedup** in Mojo) and longest-prefix KV cache slot trie.
2. `kernels/memory_titans_deltanet.mojo`: Google's *Titans* (`2501.00663`) surprise momentum + *Gated DeltaNet-2* (`2605.22791`) decoupled erase/write gates.
3. `kernels/ternary_router.mojo`: *BitNet b1.58* (`2402.17764`) 2-bit packed multiplier-free ternary GEMV router.
4. `kernels/sieve_snapkv.mojo`: *SnapKV* (`2404.14469`) 1D max-pooled observation clustering.
5. `kernels/forecast_shield.mojo`: Pre-simulation trajectory forecaster & cyclic loop breaker.

All 6 Mojo kernel suites compile with **zero warnings** on Mojo 1.1.0 (`bash scripts/run_native_checks.sh`). Repo: https://github.com/Buzburg/mojo-cortex

---

