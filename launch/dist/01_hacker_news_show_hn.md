# Show HN: Cortex – Prefrontal Cortex, Associative Memory and Safety MCP for AI Agents (25.61x Mojo speedup)

## First Comment (Post immediately after submitting URL)

Hi HN! I built `cortex` (https://github.com/Buzburg/cortex) after hitting the same four failure modes across Claude Code, Cursor, and local 7B-32B models (Ollama / RWKV-7):

1. **Token & VRAM Burn:** Agents ingest 2,500 lines of noisy `pytest`/`cargo` output or 50+ MCP tool schemas, burning API credits and blowing out 16GB-32GB local KV caches.
2. **Stale Cross-Session Memory:** RAG appends conflicting notes when project architectures change instead of cleanly overwriting obsolete key-value bindings.
3. **Repeated Failed Repairs & Destructive Loops:** Under tight context budgets, greedy top-K retrieval drops failed-attempt warnings, causing agents to repeat broken fixes 5 times in a row—or corrupt working files with no way to undo just the agent's edits without wrecking `.git` history.
4. **Local LLM Tool-Call Breakage:** Smaller local models choke on 50+ tool schemas or emit broken JSON tool calls with trailing commas and markdown fences.

### How `cortex` solves this (Zero external dependencies, 10-second MCP stdio server + Mojo 1.1.0 kernels):

- **Hybrid Neural Memory (Google's *Titans* `2501.00663` + *Gated DeltaNet-2* `2605.22791`):** Online gradient descent with surprise momentum ($S_t$) combined with decoupled erase/write gates ($\alpha_t, \beta_t$) for **1.0000 cosine key overwrite** and surgical key deletion in `835 µs`.
- **ROMS 0/1 Knapsack Context Packer (`Mojo 1.1.0`):** Dynamic programming context selector that **reserves the highest-ranked failed-attempt warning first** before packing remaining context budget. Across 400 randomized Python-vs-Mojo parity tests via `PythonModuleBuilder`, native Mojo runs in `0.171 ms` vs `4.379 ms` in Python (**`25.61x` speedup**).
- **SnapKV Context Sieve (`2404.14469`):** 1D max-pooled observation clustering that compacts 2,504-line build logs by **98.8%** (`26,386` tokens saved in `4.25 ms`) while keeping 100% of stack traces and `file:line` pointers.
- **BitNet b1.58 Ternary Tool Router (`2402.17764`):** Multiplier-free 2-bit packed (`{-1, 0, +1}`) router that prunes 80-95% of irrelevant MCP tools in `887 µs` + deterministic JSON tool-call repair.
- **Git-Safe Copy-on-Write Time Machine:** Content-addressable SHA-256 snapshots and `<5 ms` atomic workspace rollback without touching `.git`.

Works out-of-the-box with pure Python 3.9+ (`claude mcp add cortex -- python cortex.py mcp`) and includes the full Mojo 1.1.0 kernel suite (`kernels/*.mojo`). Happy to answer any questions about the Mojo 1.1.0 `PythonModuleBuilder` FFI bridge or the DeltaNet-2/Titans math!
