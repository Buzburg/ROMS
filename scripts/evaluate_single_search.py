"""Measure the one required Mojo search on frozen and real messy-document corpora."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import statistics

def summarize(rows):
    timings = sorted(row["latency_ms"] for row in rows)
    return {"queries": len(rows), "top1": sum(row["rank"] == 1 for row in rows),
            "hit5": sum(row["rank"] is not None for row in rows),
            "mrr5": sum(1 / row["rank"] if row["rank"] else 0 for row in rows) / len(rows),
            "median_ms": statistics.median(timings),
            "p95_ms": timings[min(len(timings)-1, int(len(timings)*.95))]}
from benchmarks.messy_fixture import make_documents


def score(database, cases):
    from app import rag_engine
    from app.db import get_connection
    conn=get_connection(database)
    cold,hot=[],[]
    for case in cases:
        conn.execute('DELETE FROM embedding_cache'); conn.commit()
        rag_engine._MEM_CACHE.clear(); rag_engine.clear_result_cache()
        start=time.perf_counter()
        hits=rag_engine.local_search(case['query'],limit=5,db_path=database)
        elapsed=(time.perf_counter()-start)*1000
        rank=next((i for i,h in enumerate(hits,1) if h['doc_id'] in case['relevant']),None)
        row={**case,'rank':rank,'latency_ms':elapsed,'hits':[{'doc_id':h['doc_id'],'chunk_id':h['chunk_id']} for h in hits]}
        cold.append(row)
        rag_engine.local_search(case['query'],limit=5,db_path=database)
        start=time.perf_counter(); cached=rag_engine.local_search(case['query'],limit=5,db_path=database)
        elapsed=(time.perf_counter()-start)*1000
        assert cached==hits
        hot.append({**row,'latency_ms':elapsed})
    return {'fresh':{'summary':summarize(cold),'queries':cold},'cached':{'summary':summarize(hot)}}


def main():
    work=ROOT/'scratch/search-evaluation'
    os.environ.update(ROMS_EMBEDDING_MODEL='embeddinggemma-q8',ROMS_EMBEDDING_PROVIDER='local',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    from app import config
    from app.db import get_connection,init_database
    from app.document_parse import fit_model_window
    from app.okf_loader import ingest_okf_directory,get_ingestion_status
    model=config.get_embedding_model()
    samples=[' '.join(['uncharacteristically']*400), '北極設備冷却維持測定'*200, 'αβγδ🙂é '*500]
    for sample in samples:
        pieces=fit_model_window([sample],model)
        assert all(len(model.tokenizer(piece)['input_ids'])<=model.max_seq_length for piece in pieces)
        assert pieces[0].startswith(sample[:10]) and pieces[-1].endswith(sample[-10:])
    database=work/'evaluation.db'
    frozen=json.loads((work/'chunks.json').read_text())
    conn=get_connection(database)
    assert {int(cid):(did,text) for cid,did,text in conn.execute('SELECT chunk_id,doc_id,content FROM fts_chunks')} == {int(row['chunk_id']):(row['doc_id'],row['content']) for row in frozen}
    cases=json.loads((ROOT/'benchmarks/search_feature_cases.json').read_text())['queries']
    report={'scope':'Small synthetic/manual CPU exercises; not production accuracy or speed guarantees.',
            'timing':'Loaded local EmbeddingGemma Q8, fresh query embedding per measured call; separate populated result cache measurements.',
            'token_window_check':'Long subwords, CJK and Unicode slices all fit actual model tokenizer window.',
            'frozen':score(database,cases)}
    temp=ROOT/'scratch/single-search-evaluation'
    temp.mkdir(parents=True,exist_ok=True)
    root=temp/'documents'
    labels=make_documents(root)
    database=temp/'messy.db'
    # Dedicated disposable evaluation database only.
    for suffix in ['', '-wal','-shm']:
        Path(str(database)+suffix).unlink(missing_ok=True)
    init_database(database)
    start=time.perf_counter(); count=ingest_okf_directory(root,database); elapsed=time.perf_counter()-start
    assert count==14, count
    assert get_ingestion_status(database)['failure_count']==0
    cases=[{'id':f'messy-{i}','query':query,'relevant':relevant} for i,(query,relevant) in enumerate(labels,1)]
    report['messy']={'files':count,'ingestion_seconds':elapsed,'sources':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()},**score(database,cases)}
    out=ROOT/'docs/verification/single-search-evaluation.json'
    out.write_text(json.dumps(report,indent=2))
    for corpus in ['frozen','messy']:
        print(corpus,json.dumps({key:report[corpus][key]['summary'] for key in ['fresh','cached']}),flush=True)
    print('ingestion_seconds',elapsed,flush=True)


if __name__=='__main__':
    main()
