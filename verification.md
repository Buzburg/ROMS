# Verification & Benchmark Report (`mojo-cortex` v1.1.0)

## 1. Local Toolchain &Cross-Repo Integration Summary

Inspected and integrated native Mojo 1.1.0 (`8189361e`) mechanisms from:
1. **`ROMS` (`D:\Buzburg Files\Github\ROMS`)**:
   - `select_context` (`app_mojo/context_select.mojo` -> `kernels/runtime_mojond_roms.mojo`): Bounded 0/1 dynamic-programming knapsack context packer that reserves the highest-ranked failed-attempt warning first so agents never repeat failed repairs.
   - `BinaryVector` (`app_mojo/quantized_vec.mojo` -> `kernels/runtime_mojond_roms.mojo`): 1-bit sign-quantized embeddings packing 384 `Float32` dimensions into 6 `UInt64` words (`48 bytes`, `32x` compression) with bitwise XOR + hardware popcount similarity.
   - `PythonModuleBuilder` (`app_mojo/context_bindings.mojo` -> `kernels/cortex_bindings.mojo`): Zero-copy in-process Python-to-Mojo native module bridge.
2. **`mojond` (`D:\Buzburg Files\Github\mojond` & `D:\Buzburg Files\Inference\mojond`)**:
   - `PrefixIndex` & `prompt_lookup` (`core.mojo` -> `kernels/runtime_mojond_roms.mojo`): Native token-prefix trie for KV slot selection and parameter-free greedy n-gram speculative token drafting.
   - `TokenBudget` & `kv_bytes` (`budget.mojo` -> `kernels/runtime_mojond_roms.mojo`): Live token admission controller and overflow-checked analytical KV-cache byte sizing.
3. **`FlashMojo` (`D:\Buzburg Files\Inference\FlashMojo`)**:
   - Verified local `Mojo 1.1.0 (8189361e)` compiler wrapper (`build/local-compiler.sh`) and aligned `kernels/memory_titans_deltanet.mojo` with the Gated DeltaNet state recurrence patterns (`gdn_probe.mojo`).

## 2. Native Mojo 1.1.0 Kernel Suite (`test_cortex.mojo`)

Command:
```bash
wsl --exec bash "/mnt/d/Buzburg Files/Github/mojo-cortex/scripts/run_native_checks.sh"
```

Result:
```text
PASS: All 6 native Mojo 1.1.0 kernel suites verified (Titans+DeltaNet2, BitNet, SnapKV, Shield, mojond, ROMS)
```

## 3. Python 3.14.7 <-> Mojo 1.1.0 Parity & Speedup Benchmark (`benchmarks/bench_native.mojo`)

- **Knapsack Context Packing Parity**: `400 / 400` randomized cases matched bit-for-bit.
- **Speculative Prompt Lookup Parity**: `200 / 200` randomized cases matched bit-for-bit.
- **Boundary Input Validation**: `5 / 5` invalid boundary inputs rejected across the Python/Mojo bridge.

| Case | Records / Window | Budget | Python Median (`ms`) | Mojo 1.1.0 Median (`ms`) | Speedup |
| :--- | ---: | ---: | ---: | ---: | ---: |
| `tight-20` (0/1 Knapsack) | `20` | `2,000` chars | `0.164260` | `0.017012` | **`9.66x`** |
| `standard-20` (0/1 Knapsack) | `20` | `6,000` chars | `4.379378` | `0.170983` | **`25.61x`** |
| `large-20` (0/1 Knapsack) | `20` | `18,000` chars | `20.849233` | `0.924635` | **`22.55x`** |
| `prompt_lookup_512` (Speculative Draft) | `512` (`w=4, k=4`) | `4` draft tok | `0.091843` | `0.028554` | **`3.22x`** |

## 4. Python Unit & MCP JSON-RPC 2.0 Protocol Suite (`tests/test_cortex.py`)

Command:
```bash
python tests/test_cortex.py -v
```

Result:
```text
Ran 12 tests in 0.208s — OK
```
