"""Convert once at the Python/Mojo boundary and execute native Mojo 1.1.0 kernels."""

from std.collections import List
from std.python import Python, PythonObject
from runtime_mojond_roms import select_context, prompt_lookup, kv_bytes


def pack_context(
    costs: PythonObject,
    utilities: PythonObject,
    budget: PythonObject,
    required: PythonObject
) raises -> PythonObject:
    """Native 0/1 knapsack context selector with failed-attempt warning reservation."""
    var n = len(costs)
    if n > 64 or n != len(utilities):
        raise Error("Invalid context selector dimensions")
    var native_costs = List[Int](capacity=n)
    var native_utilities = List[Int](capacity=n)
    for i in range(n):
        native_costs.append(Int(py=costs[i]))
        native_utilities.append(Int(py=utilities[i]))
    var picked = select_context(
        native_costs,
        native_utilities,
        Int(py=budget),
        Int(py=required)
    )
    var builtins = Python.import_module("builtins")
    var result = builtins.list()
    for i in range(len(picked)):
        result.append(picked[i])
    return result


def prompt_lookup_native(
    history: PythonObject,
    window: PythonObject,
    limit: PythonObject
) raises -> PythonObject:
    """Native parameter-free greedy prompt-lookup speculative drafter."""
    var n = len(history)
    var native_hist = List[Int](capacity=n)
    for i in range(n):
        native_hist.append(Int(py=history[i]))
    var drafted = prompt_lookup(native_hist, Int(py=window), Int(py=limit))
    var builtins = Python.import_module("builtins")
    var result = builtins.list()
    for i in range(len(drafted)):
        result.append(drafted[i])
    return result
