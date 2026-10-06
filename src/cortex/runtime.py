"""
mojond & ROMS Runtime Primitives for cortex:
- select_context: Bounded 0/1 knapsack context packing with failed-attempt warning reservation (ROMS)
- PrefixIndex & prompt_lookup: Token-prefix trie & greedy speculative n-gram drafting (mojond)
- TokenBudget & kv_bytes: Live token reservation & overflow-checked KV byte sizing (mojond)
- BinaryVector: 1-bit sign-quantized embeddings with bitwise XOR + popcount similarity (ROMS)
"""


def select_context(
    costs: list,
    utilities: list,
    budget: int,
    required: int = -1
) -> list:
    """
    Bounded 0/1 knapsack context packing with failed-attempt warning reservation.
    Matches the native Mojo implementation in `kernels/runtime_mojond_roms.mojo` bit-for-bit.
    """
    n = len(costs)
    if n != len(utilities) or n > 64 or budget < 0 or budget > 20000:
        raise ValueError("Invalid context selector dimensions or budget")
    if required < -1 or required >= n:
        raise ValueError("Invalid required record")
    total = 0
    for i in range(n):
        if costs[i] < 1 or costs[i] > 20000 or utilities[i] < 1 or utilities[i] > 1000000:
            raise ValueError("Invalid record cost or utility")
        total += costs[i]
    if required >= 0 and costs[required] > budget:
        raise ValueError("Required record cannot fit")
    if total <= budget:
        return list(range(n))

    remaining = budget - (costs[required] if required >= 0 else 0)
    width = remaining + 1
    scores = [0] * width
    decisions = [False] * (n * width)

    for i in range(n):
        if i == required:
            continue
        weight = costs[i]
        value = utilities[i]
        for capacity in range(remaining, weight - 1, -1):
            proposed = scores[capacity - weight] + value
            if proposed > scores[capacity]:
                scores[capacity] = proposed
                decisions[i * width + capacity] = True

    chosen = [i == required for i in range(n)]
    capacity = remaining
    for i in range(n - 1, -1, -1):
        if decisions[i * width + capacity]:
            chosen[i] = True
            capacity -= costs[i]

    return [i for i in range(n) if chosen[i]]


def prompt_lookup(history: list, window: int, limit: int) -> list:
    """
    Parameter-free greedy prompt lookup for speculative n-gram drafting.
    Matches `kernels/runtime_mojond_roms.mojo` bit-for-bit.
    """
    if window < 1 or limit < 1 or len(history) <= window:
        return []
    suffix = len(history) - window
    for offset in range(suffix):
        start = suffix - offset - 1
        matches = True
        for j in range(window):
            if history[start + j] != history[suffix + j]:
                matches = False
                break
        if matches:
            count = min(limit, len(history) - start - window)
            return [history[start + window + j] for j in range(count)]
    return []


def kv_bytes(
    layers: int,
    heads: int,
    head_dim: int,
    tokens: int,
    bytes_per_element: int
) -> int:
    """Overflow-checked analytical KV cache byte calculator."""
    if min(layers, heads, head_dim, tokens, bytes_per_element) < 1:
        raise ValueError("KV dimensions must be positive")
    size = 2
    for dimension in (layers, heads, head_dim, tokens, bytes_per_element):
        if size > 9_223_372_036_854_775_807 // dimension:
            raise OverflowError("KV size overflow")
        size *= dimension
    return size


class PrefixIndex:
    """Token-prefix trie for shared prompt prefixes and cache slot selection."""
    def __init__(self):
        self.nodes = [[-1, -1, -1, -1]]  # [token, child, sibling, slot]

    def insert(self, tokens: list, count: int, slot: int):
        parent = 0
        for i in range(count):
            node = self.nodes[parent][1]
            while node >= 0:
                if self.nodes[node][0] == tokens[i]:
                    break
                node = self.nodes[node][2]
            if node < 0:
                node = len(self.nodes)
                self.nodes.append([tokens[i], -1, self.nodes[parent][1], slot])
                self.nodes[parent][1] = node
            self.nodes[node][3] = slot
            parent = node

    def match(self, tokens: list) -> tuple:
        parent = 0
        slot = -1
        count = 0
        for i in range(max(0, len(tokens) - 1)):
            node = self.nodes[parent][1]
            while node >= 0:
                if self.nodes[node][0] == tokens[i]:
                    break
                node = self.nodes[node][2]
            if node < 0:
                break
            slot = self.nodes[node][3]
            count += 1
            parent = node
        return slot, count


class TokenBudget:
    """Live token reservation and admission controller."""
    def __init__(self, capacity: int):
        if capacity < 1:
            raise ValueError("token capacity must be positive")
        self.capacity = capacity
        self.reserved = 0

    def available(self, amount: int) -> bool:
        return 0 < amount <= (self.capacity - self.reserved)

    def acquire(self, amount: int):
        if not self.available(amount):
            raise RuntimeError("live token capacity exhausted")
        self.reserved += amount

    def release(self, amount: int):
        if amount < 1 or amount > self.reserved:
            raise ValueError("invalid token reservation release")
        self.reserved -= amount


class BinaryVector:
    """1-bit sign-quantized embedding (48 bytes for 384 dimensions, 32x compression)."""
    def __init__(self, vec: list):
        self.dim = len(vec)
        num_words = (self.dim + 63) // 64
        self.words = [0] * num_words
        for i, val in enumerate(vec):
            if val >= 0.0:
                self.words[i // 64] |= (1 << (i % 64))

    def hamming_distance(self, other: "BinaryVector") -> int:
        return sum((w1 ^ w2).bit_count() for w1, w2 in zip(self.words, other.words))

    def similarity(self, other: "BinaryVector") -> float:
        return 1.0 - (self.hamming_distance(other) / max(1, self.dim))
