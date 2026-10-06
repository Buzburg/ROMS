#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPILER="/mnt/d/Buzburg Files/Inference/FlashMojo/build/local-compiler.sh"
cd "$ROOT"
export PYTHONPATH="$ROOT:$ROOT/src"
"$COMPILER" -I "$ROOT/kernels" "$ROOT/test_cortex.mojo"
"$COMPILER" -I "$ROOT/kernels" "$ROOT/benchmarks/bench_native.mojo"
