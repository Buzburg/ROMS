"""Exercise real quantized model inference and ROMS retrieval in a temporary index.

Run after installing requirements.txt. First run downloads the
pinned public model; subsequent runs work with HF_HUB_OFFLINE=1.
"""
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    import numpy as np
    from app.config import get_embedding_model, compute_embedding_vector
    from app.db import init_database, get_connection
    from app.document_parse import fit_model_window
    from app.okf_loader import ingest_document_file
    from app.rag_engine import vector_search, local_search
    model = get_embedding_model()
    documents = [
        'Mars is known as the Red Planet because of its rusty surface.',
        'Banana bread uses ripe fruit, flour and eggs baked in an oven.',
        'Password resets require an email verification link to access your account.',
    ]
    questions = ['Which planet has a reddish surface?', 'How do I bake banana bread?',
                 'How can I recover my login password?']
    vectors = model.encode(documents)
    assert vectors.shape == (3, 768) and np.isfinite(vectors).all()
    np.testing.assert_allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-5)
    for index, question in enumerate(questions):
        query = np.array(compute_embedding_vector(question))
        assert int(np.argmax(vectors @ query)) == index
    sample = '北極設備冷却維持測定 ' * 500
    pieces = fit_model_window([sample], model)
    assert len(pieces) > 1 and pieces[-1].endswith(sample[-10:])
    assert model.encode(pieces).shape == (len(pieces), 768)
    with tempfile.TemporaryDirectory(prefix='roms-gemma-') as temp:
        root = Path(temp)
        database = root / 'test.db'
        init_database(database)
        for index, text in enumerate(documents):
            path = root / f'{index}.txt'
            path.write_text(text)
            assert ingest_document_file(path, database)
            assert not ingest_document_file(path, database)
        for index, question in enumerate(questions):
            for search in (vector_search, local_search):
                hits = search(question, limit=3, db_path=database)
                assert hits[0]['doc_id'] == f'{index}.txt', hits
        get_connection(database).close()
    print('PASS: q8 CPU inference, normalized 768d vectors, three semantic rankings,')
    print('Unicode passage splitting, ingestion/idempotence, vector and hybrid search.')


if __name__ == '__main__':
    main()
