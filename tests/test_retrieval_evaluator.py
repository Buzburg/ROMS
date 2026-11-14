"""Evaluation gives each relevant document credit once, regardless of chunks."""
import math

import pytest

from scripts.evaluate_single_search import relevance


def test_duplicate_passages_cannot_inflate_retrieval_metrics():
    hits = [dict(doc_id=doc) for doc in ['a', 'a', 'b', 'other', 'c']]
    result = relevance(hits, ['a', 'b', 'missing'])
    assert result['rank'] == 1
    assert result['recall5'] == pytest.approx(2 / 3)
    assert result['ndcg5'] == pytest.approx((1 + 1 / math.log2(4)) / (1 + 1 / math.log2(3) + 1 / math.log2(4)))


def test_irrelevant_evidence_scores_zero():
    assert relevance([dict(doc_id='wrong')], ['correct']) == dict(rank=None, recall5=0, ndcg5=0)


def test_generated_fixtures_reuse_exact_bytes_and_reject_changes(tmp_path):
    from scripts.evaluate_single_search import generated_fixture
    folder = tmp_path / 'frozen'
    def build(directory):
        (directory / 'example.txt').write_bytes(b'original evidence')
        return [dict(id='q', query='original', relevant=['example.txt'])]
    documents, cases = generated_fixture(folder, 'recipe-v1', build)
    again, labels = generated_fixture(folder, 'recipe-v1', lambda _: pytest.fail('Frozen input regenerated'))
    assert again == documents and labels == cases
    documents[0][0].write_bytes(b'changed evidence')
    with pytest.raises(ValueError, match='Frozen fixture changed'):
        generated_fixture(folder, 'recipe-v1', build)


def test_fixture_recipe_change_requires_new_directory(tmp_path):
    from scripts.evaluate_single_search import generated_fixture
    folder = tmp_path / 'frozen'
    generated_fixture(folder, 'old', lambda _: [])
    with pytest.raises(ValueError, match='recipe changed'):
        generated_fixture(folder, 'new', lambda _: [])
