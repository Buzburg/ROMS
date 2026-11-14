"""Reproducible local retrieval evaluation; builds isolated indexes from source."""
import argparse
import hashlib
import json
from contextlib import ExitStack
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def summarize(rows):
    timings = sorted(row['latency_ms'] for row in rows)
    return {'queries': len(rows), 'top1': sum(row['rank'] == 1 for row in rows),
            'hit5': sum(row['rank'] is not None for row in rows),
            'mrr5': statistics.mean(1 / row['rank'] if row['rank'] else 0 for row in rows),
            'recall5': statistics.mean(row['recall5'] for row in rows),
            'ndcg5': statistics.mean(row['ndcg5'] for row in rows),
            'median_ms': statistics.median(timings),
            'p95_ms': timings[min(len(timings) - 1, math.ceil(len(timings) * .95) - 1)]}


def relevance(hits, relevant):
    """Document-level metrics: repeated chunks of one document get one credit."""
    relevant, seen, gains = set(relevant), set(), []
    for hit in hits[:5]:
        doc = hit['doc_id']
        gains.append(int(doc in relevant and doc not in seen))
        seen.add(doc)
    rank = next((i for i, gain in enumerate(gains, 1) if gain), None)
    ideal = sum(1 / math.log2(i + 2) for i in range(min(5, len(relevant))))
    return {'rank': rank, 'recall5': len(seen & relevant) / len(relevant) if relevant else None,
            'ndcg5': sum(g / math.log2(i + 2) for i, g in enumerate(gains)) / ideal if ideal else None}


def score(database, cases):
    from app import rag_engine
    from app.db import get_connection
    conn = get_connection(database)
    cold, hot = [], []
    for case in cases:
        conn.execute('DELETE FROM embedding_cache')
        conn.commit()
        rag_engine._MEM_CACHE.clear()
        rag_engine.clear_result_cache()
        start = time.perf_counter()
        hits = rag_engine.local_search(case['query'], limit=5, db_path=database)
        elapsed = (time.perf_counter() - start) * 1000
        row = {**case, **relevance(hits, case['relevant']), 'latency_ms': elapsed,
               'hits': [dict(doc_id=h['doc_id'], chunk_id=h['chunk_id'], source=h.get('source', {})) for h in hits]}
        if 'answer' in case:
            row['answer_in_relevant_evidence'] = any(h['doc_id'] in case['relevant'] and case['answer'] in h['content'] for h in hits)
        cold.append(row)
        rag_engine.local_search(case['query'], limit=5, db_path=database)
        start = time.perf_counter()
        cached = rag_engine.local_search(case['query'], limit=5, db_path=database)
        assert cached == hits, 'Cached retrieval changed evidence'
        hot.append({**row, 'latency_ms': (time.perf_counter() - start) * 1000})
    return {'fresh': {'summary': summarize(cold), 'queries': cold},
            'cached': {'summary': summarize(hot)}}


def source_hashes(paths, root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(paths)}


def generated_fixture(directory, recipe_hash, build):
    """Reuse exact fixture bytes, including timestamps inside Office/PDF files."""
    manifest_path = directory / 'fixture-manifest.json'
    if directory.exists():
        if not manifest_path.is_file():
            raise ValueError('Fixture directory already exists without a manifest; choose a new directory')
        manifest = json.loads(manifest_path.read_text())
        if manifest['recipe_sha256'] != recipe_hash:
            raise ValueError('Fixture recipe changed; choose a new fixture directory')
        documents = []
        for name, digest in manifest['files'].items():
            if Path(name).name != name or name in {'.', '..'}:
                raise ValueError('Invalid fixture filename')
            path = directory / name
            if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError('Frozen fixture changed; comparison refused')
            documents.append((path, name))
        return documents, manifest['queries']
    directory.mkdir(parents=True)
    cases = build(directory)
    documents = [(path, path.name) for path in sorted(directory.iterdir()) if path.is_file()]
    manifest = {'recipe_sha256': recipe_hash, 'files': source_hashes([p for p, _ in documents], directory), 'queries': cases}
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    return documents, cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'scratch/search-evaluation/results.json')
    parser.add_argument('--corpus', choices=['all', 'repository', 'messy', 'structured'], default='all')
    parser.add_argument('--fixtures', type=Path, help='Create or reuse a frozen generated-fixture directory for byte-identical comparisons')
    parser.add_argument('--implementation-root', type=Path, default=ROOT,
                        help='Optional baseline checkout; fixtures always come from this evaluator')
    args = parser.parse_args()
    implementation = args.implementation_root.resolve()
    sys.path.insert(0, str(implementation))
    os.environ.setdefault('HF_HUB_OFFLINE', '1')
    os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')
    from app import config
    from app.db import init_database, get_connection
    from app.okf_loader import ingest_document_file
    from app.embedding_space import identity
    model = config.get_embedding_model()  # cold model startup is outside query timings
    code_before = source_hashes(implementation.joinpath('app').glob('*.py'), implementation)
    report = {'scope': 'Small synthetic/manual CPU fixtures, not a production benchmark or general quality guarantee.',
              'timing': 'Loaded local EmbeddingGemma 2 Q8; fresh query embeddings, with cached results measured separately.',
              'model_identity': json.loads(identity()), 'implementation': str(implementation),
              'implementation_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=implementation, text=True).strip(),
              'python': sys.version, 'app_source_sha256': code_before,
              'evaluator_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'corpora': {}}
    with tempfile.TemporaryDirectory(prefix='roms-evaluation-') as temporary, ExitStack() as resources:
        work = Path(temporary)
        for name in ['repository', 'messy', 'structured']:
            if args.corpus not in {'all', name}:
                continue
            if name == 'repository':
                fixture = json.loads((ROOT / 'benchmarks/search_feature_cases.json').read_text())
                documents = [(ROOT / path, path) for path in fixture['documents']]
                cases = fixture['queries']
                corpus_root = ROOT
            elif name == 'messy':
                from benchmarks.messy_fixture import make_documents
                corpus_root = (args.fixtures or work) / 'messy'
                def build_messy(directory):
                    return [dict(id=f'messy-{i}', query=q, relevant=r)
                            for i, (q, r) in enumerate(make_documents(directory), 1)]
                recipe = hashlib.sha256((ROOT / 'benchmarks/messy_fixture.py').read_bytes()).hexdigest()
                documents, cases = generated_fixture(corpus_root, recipe, build_messy)
            else:
                recipe_path = ROOT / 'benchmarks/structured_search_cases.json'
                fixture = json.loads(recipe_path.read_text())
                corpus_root = (args.fixtures or work) / 'structured'
                def build_structured(directory):
                    for filename, text in fixture['documents'].items():
                        (directory / filename).write_text(text, encoding='utf-8')
                    return fixture['queries']
                documents, cases = generated_fixture(corpus_root, hashlib.sha256(recipe_path.read_bytes()).hexdigest(), build_structured)
            database = work / f'{name}.db'
            init_database(database)
            resources.callback(get_connection(database).close)
            before = source_hashes([path for path, _ in documents], corpus_root)
            start = time.perf_counter()
            count = sum(ingest_document_file(path, database, doc_id=doc_id) for path, doc_id in documents)
            assert count == len(documents), 'Evaluation corpus was not completely ingested'
            ingestion_seconds = time.perf_counter() - start
            assert before == source_hashes([path for path, _ in documents], corpus_root), 'Corpus changed during evaluation'
            measured = score(database, cases)
            report['corpora'][name] = {'files': count, 'ingestion_seconds': ingestion_seconds,
                                      'source_sha256': before,
                                      'labels_sha256': hashlib.sha256(json.dumps(cases, sort_keys=True).encode()).hexdigest(), **measured}
            print(name, json.dumps(measured['fresh']['summary']), flush=True)
    assert code_before == source_hashes(implementation.joinpath('app').glob('*.py'), implementation), 'Implementation changed during evaluation'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(f'Report: {args.output}', flush=True)


if __name__ == '__main__':
    main()
