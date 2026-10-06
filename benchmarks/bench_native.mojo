"""Run parity and benchmark checks through the real Python/Mojo 1.1.0 boundary."""

from std.python import Python
from std.python.bindings import PythonModuleBuilder
from cortex_bindings import pack_context, prompt_lookup_native


def main() raises:
    var builder = PythonModuleBuilder("cortex_native_bench")
    builder.def_function[pack_context]("pack_context")
    builder.def_function[prompt_lookup_native]("prompt_lookup_native")
    var native = builder.finalize()
    var benchmark = Python.import_module("benchmarks.bench_native_bridge")
    benchmark.run(native.pack_context, native.prompt_lookup_native)
