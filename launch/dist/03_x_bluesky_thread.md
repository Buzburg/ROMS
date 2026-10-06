# X / Twitter & Bluesky 7-Post Launch Thread

1/ Every AI coding agent (Claude Code, Cursor, Windsurf) & local LLM (Ollama, RWKV-7) hits the same 4 walls:
• 25k token log burn
• Stale cross-session memory
• Repeating failed repairs in loops
• Broken local JSON tool calls

Meet cortex (Mojo 1.1.0 + Python MCP):
https://github.com/Buzburg/cortex

---

2/ Why do agents repeat the exact same failed fix 5 times in a row?

Because greedy top-K context retrieval drops failed-attempt warnings when budgets tighten.

cortex uses a native Mojo 1.1.0 0/1 Knapsack solver that reserves failed-attempt warnings FIRST—running in 0.171ms (25.61x faster than Python).

---

3/ What about cross-session memory when your codebase changes?

Standard RAG appends conflicting notes.

cortex fuses Google's Titans (2501.00663) surprise momentum with Gated DeltaNet-2 (2605.22791) decoupled erase/write gates—giving 1.0000 cosine key overwrite & surgical erasure in 835 µs.

---

4/ Stop feeding 2,500 lines of noisy `pytest` / `cargo` output into your context window.

Our SnapKV (2404.14469) Context Sieve uses 1D max-pooled observation clustering to compact logs by 98.8% (26,386 tokens saved in 4.25 ms) while keeping 100% of tracebacks & file:line pointers.

---

5/ Running local 7B–32B models on 16GB–32GB VRAM?

• BitNet b1.58 (2402.17764) 2-bit ternary router prunes 80-95% of irrelevant MCP tools in 887 µs using zero multiplications.
• Deterministic JSON repair fixes trailing commas, single quotes & stringified ints in <50 µs.

---

6/ Worried about an agent corrupting working files during a multi-file refactor?

cortex includes a Content-Addressable SHA-256 Copy-on-Write Time Machine (`cortex_snapshot_create` / `rewind`) that atomically restores your workspace in <5 ms WITHOUT touching `.git` history.

---

7/ Connect `cortex` to Claude Code, Cursor, or Windsurf in 10 seconds:

`claude mcp add cortex -- python cortex.py mcp`

• Zero external pip dependencies
• 6 native Mojo 1.1.0 kernel suites
• 600/600 Python-Mojo parity checks passing

Star & try it here: https://github.com/Buzburg/cortex
