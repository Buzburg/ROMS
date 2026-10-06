"""Mojo-cortex Kernel 2: BitNet b1.58 Multiplier-Free Ternary Tool Router."""

from std.collections import List

comptime ROUTER_DIM: Int = 128


@fieldwise_init
struct TernaryToolSignature(Copyable, Movable):
    var tool_id: Int
    var packed_weights: List[UInt8]   # 128 ternary values packed into 32 bytes
    var scale_gamma: Float32


def score_tool_multiplier_free(
    sig: TernaryToolSignature,
    query_int8: List[Int]
) -> Float32:
    """Computes dot product between 2-bit packed ternary tool embedding and Int8 query vector."""
    var int_acc: Int = 0
    for c in range(ROUTER_DIM):
        var byte_idx = c // 4
        var shift = (c % 4) * 2
        var code = Int((sig.packed_weights[byte_idx] >> UInt8(shift)) & UInt8(0x03))
        var w_ter = code - 1  # {-1, 0, +1}
        if w_ter == 1:
            int_acc += query_int8[c]
        elif w_ter == -1:
            int_acc -= query_int8[c]

    return Float32(int_acc) * sig.scale_gamma


def main():
    print("mojo-cortex Kernel 2 (BitNet b1.58 Ternary Router) initialized.")
