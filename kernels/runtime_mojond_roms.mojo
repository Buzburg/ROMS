"""Native mojond & ROMS primitives: PrefixIndex, prompt_lookup, TokenBudget, select_context, and BinaryVector."""

from std.collections import List


@fieldwise_init
struct Node(Copyable, Movable):
    var token: Int
    var child: Int
    var sibling: Int
    var slot: Int


struct PrefixIndex:
    """Native token-prefix trie for shared prompt prefixes and slot reuse (from mojond)."""
    var nodes: List[Node]

    def __init__(out self):
        self.nodes = List[Node]()
        self.nodes.append(Node(-1, -1, -1, -1))

    def insert(mut self, tokens: List[Int], count: Int, slot: Int):
        var parent = 0
        for i in range(count):
            var node = self.nodes[parent].child
            while node >= 0:
                if self.nodes[node].token == tokens[i]:
                    break
                node = self.nodes[node].sibling
            if node < 0:
                node = len(self.nodes)
                self.nodes.append(Node(tokens[i], -1, self.nodes[parent].child, slot))
                self.nodes[parent].child = node
            self.nodes[node].slot = slot
            parent = node

    def match(self, tokens: List[Int]) -> Tuple[Int, Int]:
        var parent = 0
        var slot = -1
        var count = 0
        for i in range(max(0, len(tokens) - 1)):
            var node = self.nodes[parent].child
            while node >= 0:
                if self.nodes[node].token == tokens[i]:
                    break
                node = self.nodes[node].sibling
            if node < 0:
                break
            slot = self.nodes[node].slot
            count += 1
            parent = node
        return slot, count


def prompt_lookup(history: List[Int], window: Int, limit: Int) -> List[Int]:
    """Parameter-free greedy prompt lookup for speculative n-gram drafting (from mojond)."""
    var result = List[Int]()
    if window < 1 or limit < 1 or len(history) <= window:
        return result^
    var suffix = len(history) - window
    for offset in range(suffix):
        var start = suffix - offset - 1
        var matches = True
        for j in range(window):
            if history[start + j] != history[suffix + j]:
                matches = False
                break
        if matches:
            for j in range(min(limit, len(history) - start - window)):
                result.append(history[start + window + j])
            break
    return result^


def kv_bytes(
    layers: Int,
    heads: Int,
    head_dim: Int,
    tokens: Int,
    bytes_per_element: Int
) raises -> Int:
    """Overflow-checked analytical KV cache byte calculator (from mojond)."""
    if min(layers, heads, head_dim, tokens, bytes_per_element) < 1:
        raise Error("KV dimensions must be positive")
    var size = 2
    for dimension in [layers, heads, head_dim, tokens, bytes_per_element]:
        if size > 9_223_372_036_854_775_807 // dimension:
            raise Error("KV size overflow")
        size *= dimension
    return size


struct TokenBudget:
    """Live token admission and reservation controller (from mojond)."""
    var capacity: Int
    var reserved: Int

    def __init__(out self, capacity: Int) raises:
        if capacity < 1:
            raise Error("token capacity must be positive")
        self.capacity = capacity
        self.reserved = 0

    def available(self, amount: Int) -> Bool:
        return amount > 0 and amount <= self.capacity - self.reserved

    def acquire(mut self, amount: Int) raises:
        if not self.available(amount):
            raise Error("live token capacity exhausted")
        self.reserved += amount

    def release(mut self, amount: Int) raises:
        if amount < 1 or amount > self.reserved:
            raise Error("invalid token reservation release")
        self.reserved -= amount


def select_context(
    costs: List[Int],
    utilities: List[Int],
    budget: Int,
    required: Int = -1
) raises -> List[Int]:
    """Bounded 0/1 knapsack context packing with failed-attempt warning reservation (from ROMS)."""
    var n = len(costs)
    if n != len(utilities) or n > 64 or budget < 0 or budget > 20000:
        raise Error("Invalid context selector dimensions or budget")
    if required < -1 or required >= n:
        raise Error("Invalid required record")
    var total = 0
    for i in range(n):
        if costs[i] < 1 or costs[i] > 20000 or utilities[i] < 1 or utilities[i] > 1000000:
            raise Error("Invalid record cost or utility")
        total += costs[i]
    var selected = List[Int]()
    if required >= 0 and costs[required] > budget:
        raise Error("Required record cannot fit")
    if total <= budget:
        for i in range(n):
            selected.append(i)
        return selected^
    var remaining = budget
    if required >= 0:
        remaining -= costs[required]
    var width = remaining + 1
    var scores = List[Int](capacity=width)
    for _ in range(width):
        scores.append(0)
    var decisions = List[Bool](capacity=n * width)
    for _ in range(n * width):
        decisions.append(False)
    for i in range(n):
        if i == required:
            continue
        var weight = costs[i]
        var value = utilities[i]
        for capacity in range(remaining, weight - 1, -1):
            var proposed = scores[capacity - weight] + value
            if proposed > scores[capacity]:
                scores[capacity] = proposed
                decisions[i * width + capacity] = True
    var chosen = List[Bool](capacity=n)
    for i in range(n):
        chosen.append(i == required)
    var capacity = remaining
    for i in range(n - 1, -1, -1):
        if decisions[i * width + capacity]:
            chosen[i] = True
            capacity -= costs[i]
    for i in range(n):
        if chosen[i]:
            selected.append(i)
    return selected^


struct BinaryVector(Movable, Copyable):
    """1-bit sign-quantized embedding (48 bytes for 384 dims, 32x compression, from ROMS)."""
    var words: List[UInt64]
    var dim: Int

    def __init__(out self, dim: Int = 384):
        self.dim = dim
        var num_words = (dim + 63) // 64
        self.words = List[UInt64](capacity=num_words)
        for _ in range(num_words):
            self.words.append(0)

    def __copyinit__(out self, other: Self):
        self.dim = other.dim
        self.words = List[UInt64](capacity=len(other.words))
        for i in range(len(other.words)):
            self.words.append(other.words[i])

    def __moveinit__(out self, mut other: Self):
        self.dim = other.dim
        self.words = other.words^

    def set_bit(mut self, index: Int, val: Bool):
        if val:
            var word_idx = index // 64
            var bit_idx = UInt64(index % 64)
            self.words[word_idx] = self.words[word_idx] | (UInt64(1) << bit_idx)

    def hamming_distance(self, other: BinaryVector) -> Int:
        """Calculates bit difference between two binary vectors."""
        var total_diff: Int = 0
        for i in range(len(self.words)):
            var diff_word = self.words[i] ^ other.words[i]
            var w = diff_word
            while w > 0:
                total_diff += Int(w & 1)
                w = w >> 1
        return total_diff

    def similarity(self, other: BinaryVector) -> Float32:
        """Returns normalized Hamming similarity between 0.0 and 1.0."""
        var dist = self.hamming_distance(other)
        return 1.0 - (Float32(dist) / Float32(self.dim))


def binarize_embedding(vec: List[Float32]) -> BinaryVector:
    """Converts a continuous float32 embedding vector into a 1-bit binary representation."""
    var b_vec = BinaryVector(len(vec))
    for i in range(len(vec)):
        b_vec.set_bit(i, vec[i] >= 0.0)
    return b_vec^
