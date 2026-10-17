"""Real compiled Mojo/Python parity. A forced Mojo run may never silently skip."""
import os
import random
import string

import pytest
from app import search_native, zgsearch


@pytest.fixture
def native():
    return search_native.kernels()


def test_unicode_typo_and_top_k_parity(native):
    rng = random.Random(1938)
    alphabet = string.ascii_lowercase + 'éßø你🙂'
    terms = ['damage', 'damaged', 'replacement', 'überprüfung', 'überprufung', '你好吗', '🙂test']
    terms += [''.join(rng.choices(alphabet, k=rng.randint(1, 18))) for _ in range(2041)]
    for query in ['damagd', 'replacment', 'überprufung', '你好吗', '🙂test'] + terms[7:57]:
        eligible = [term for term in terms if abs(len(term) - len(query)) <= 2]
        expected = []
        for i, term in enumerate(eligible):
            matched, score = zgsearch._fuzzy_token_match(query, term)
            if matched and term != query:
                expected.append((score, term, i))
        expected.sort(key=lambda item: (-item[0], item[1]))
        assert native.expand(query, eligible) == [item[2] for item in expected[:16]]


def test_rank_fusion_parity_with_ties_orphans_and_duplicates(native):
    rng = random.Random(800)
    for _ in range(100):
        routes = [[rng.randint(-1, 55) for _ in range(rng.randint(0, 100))] for _ in range(2)]
        expected = {}
        for column, route in enumerate(routes):
            for rank, key in enumerate(route, 1):
                if key == -1:
                    continue
                entry = expected.setdefault(key, [key, 0.0, 0, 0])
                entry[1] += 1 / (60 + rank)
                entry[2 + column] = rank
        limit = rng.randint(1, 100)
        expected = sorted(expected.values(), key=lambda row: row[1], reverse=True)[:limit]
        actual = native.fuse(*routes, limit)
        assert [list(row) for row in actual] == expected


def test_native_bounds_are_enforced(native):
    with pytest.raises(Exception, match='Too many'):
        native.expand('query', ['word'] * 2049)
    with pytest.raises(Exception, match='bounded'):
        native.expand('x' * 129, [])
    with pytest.raises(Exception, match='Too many'):
        native.fuse([0] * 301, [], 1)
    with pytest.raises(Exception, match='bounded'):
        native.fuse([], [], 0)


def test_native_passages_retain_unicode_and_enforce_tail_bound(native):
    text = '北極🙂é' * 600
    parts = native.passages(text)
    assert ''.join(parts) == text
    assert max(map(len, parts)) <= 768
    assert native.passages('OK\n\nx') == ['OK', 'x']
    with pytest.raises(Exception, match='too many passages'):
        native.passages('x\n\n' * 20000 + 'tail')
