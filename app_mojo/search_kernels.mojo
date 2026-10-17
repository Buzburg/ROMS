"""Native Unicode typo scoring and stable reciprocal-rank fusion; no Python calls."""


def codepoints(text: String) -> List[Int]:
    var result = List[Int]()
    for cp in text.codepoints():
        result.append(Int(cp))
    return result^


def edit_distance(left: List[Int], right: List[Int]) -> Int:
    var previous = List[Int]()
    for j in range(len(right) + 1):
        previous.append(j)
    var current = previous.copy()
    for i in range(len(left)):
        current[0] = i + 1
        for j in range(len(right)):
            var replace = previous[j] + Int(left[i] != right[j])
            current[j + 1] = min(current[j] + 1, min(previous[j + 1] + 1, replace))
        var swap = previous^
        previous = current^
        current = swap^
    return previous[len(right)]


def match_score(query: List[Int], target: List[Int]) -> Float64:
    var nq = len(query)
    var nt = len(target)
    var prefix = nt >= nq
    for i in range(min(nq, nt)):
        if query[i] != target[i]:
            prefix = False
            break
    if nq == nt and prefix:
        return 1.0
    if nq <= 3:
        return 0.9 if prefix else 0.0
    var allowed = 1 if nq <= 5 else 2
    if abs(nq - nt) > allowed:
        return 0.85 if prefix else 0.0
    var distance = edit_distance(query, target)
    if distance <= allowed:
        return max(0.5, 1.0 - Float64(distance) / Float64(max(nq, nt)))
    return 0.85 if prefix else 0.0


def expand_terms(query: String, terms: List[String]) raises -> List[Int]:
    if query.count_codepoints() > 128 or len(terms) > 2048:
        raise Error("Typo expansion exceeds bounded input size")
    var points = codepoints(query)
    var indices = List[Int]()
    var scores = List[Float64]()
    for i in range(len(terms)):
        if terms[i] == query:
            continue
        if terms[i].count_codepoints() > 130:
            raise Error("Vocabulary term exceeds bounded input size")
        var score = match_score(points, codepoints(terms[i]))
        if score <= 0:
            continue
        var pos = 0
        while pos < len(indices):
            if score > scores[pos] or (score == scores[pos] and terms[i] < terms[indices[pos]]):
                break
            pos += 1
        if pos >= 16:
            continue
        if len(indices) < 16:
            indices.append(i)
            scores.append(score)
        for j in range(len(indices) - 1, pos, -1):
            indices[j] = indices[j - 1]
            scores[j] = scores[j - 1]
        indices[pos] = i
        scores[pos] = score
    return indices^


@fieldwise_init
struct RankedHit(Copyable, Movable):
    var key: Int
    var score: Float64
    var lexical_rank: Int
    var vector_rank: Int


def fuse_ranks(lexical: List[Int], vectors: List[Int], limit: Int) raises -> List[RankedHit]:
    if len(lexical) > 300 or len(vectors) > 300 or limit < 1 or limit > 300:
        raise Error("Rank fusion exceeds bounded input size")
    var hits = List[RankedHit]()
    var positions = Dict[Int, Int]()
    for route in range(2):
        var count = len(lexical) if route == 0 else len(vectors)
        for i in range(count):
            var key = lexical[i] if route == 0 else vectors[i]
            if key == -1:
                continue
            if key not in positions:
                positions[key] = len(hits)
                hits.append(RankedHit(key, 0.0, 0, 0))
            var index = positions[key]
            hits[index].score += 1.0 / Float64(61 + i)
            if route == 0:
                hits[index].lexical_rank = i + 1
            else:
                hits[index].vector_rank = i + 1
    # Bounded top-k insertion preserves first-seen order on ties, matching Python.
    var selected = List[RankedHit]()
    for hit in hits:
        var pos = 0
        while pos < len(selected) and selected[pos].score >= hit.score:
            pos += 1
        if pos >= limit:
            continue
        if len(selected) < limit:
            selected.append(hit.copy())
        for j in range(len(selected) - 1, pos, -1):
            selected[j] = selected[j - 1].copy()
        selected[pos] = hit.copy()
    return selected^
