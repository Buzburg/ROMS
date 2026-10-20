"""Real parsers/OCR and atomic messy-document intake with compiled Mojo kernels."""
import json
import os
import threading
import time
import pytest
from app import document_parse, okf_loader, source_library
from app.db import get_connection
from test_ingestion_quality import setup_ingestion


@pytest.mark.parametrize('encoding', ['utf-8-sig', 'utf-16', 'utf-16-le', 'utf-16-be', 'utf-32', 'cp1252'])
def test_encodings_controls_and_short_passages(tmp_path, encoding):
    path = tmp_path/'note.txt'
    original = 'Café\r\nOK\x01 next\u00a0step'.encode(encoding)
    path.write_bytes(original)
    parsed = document_parse.parse_document(path)
    assert 'Café\nOK  next step' == parsed.text
    assert parsed.chunks and path.read_bytes() == original


@pytest.mark.parametrize(('name','text','expected','note'), [
    ('bad.md','---\ntitle: [broken\n---\nTiny fact', 'Tiny fact', 'Malformed frontmatter'),
    ('meta.md','---\ntitle: [a,b]\ntype: 7\n---\nShort', 'Short', 'Invalid title'),
    ('bad.json','{"broken": needle unclosed', 'needle unclosed', 'Malformed JSON'),
    ('rows.jsonl','{}\n\n{broken: zircon}\n{}', 'Line 3: {broken: zircon}', 'Malformed JSONL'),
    ('bad.csv','a,b\n"unclosed,needle', 'unclosed,needle', 'Malformed CSV'),
    ('rows.tsv','a\ta\t\n1\t2\t3\tbonus\n4', 'Column_4: bonus', 'Uneven CSV'),
])
def test_broken_records_preserve_evidence(tmp_path, name, text, expected, note):
    path=tmp_path/name; path.write_text(text)
    parsed=document_parse.parse_document(path)
    assert expected in '\n'.join(parsed.chunks)
    assert any(note in item for item in parsed.notes)


def test_html_excludes_scripts_and_binary_is_rejected(tmp_path):
    path=tmp_path/'page.html'; path.write_text('<h1>Hello</h1><script>secretcode</script><p>World &amp; sky</p>')
    content=' '.join(document_parse.parse_document(path).chunks)
    assert 'secretcode' not in content and 'World & sky' in content
    path=tmp_path/'fake.txt'; path.write_bytes(b'%PDF-binary')
    with pytest.raises(ValueError, match='Binary document'):
        document_parse.parse_document(path)


def test_office_pdf_and_actual_local_ocr(tmp_path):
    from benchmarks.messy_fixture import make_documents
    make_documents(tmp_path)
    expected={'warranty.docx':['eighteen months','555-0137','4826'],
              'orders.xlsx':['Emerald pump','91234','formula, no cached value','=1+2'],
              'safety.pptx':['northern courtyard'], 'meeting.odt':['Wednesday'],
              'inspection.pdf':['Copper turbine'], 'scan.pdf':['Violet','4826'],
              'scan.png':['Violet','4826'], 'frames.tiff':['frame 1','frame 2','4826']}
    for name, needles in expected.items():
        path=tmp_path/name; original=path.read_bytes()
        parsed=document_parse.parse_document(path)
        content='\n'.join(parsed.chunks)
        assert all(needle in content for needle in needles), (name,content)
        assert path.read_bytes() == original


def test_folder_failures_recovery_metadata_and_fast_unchanged(tmp_path, monkeypatch):
    database, model, _=setup_ingestion(tmp_path, monkeypatch)
    root=tmp_path/'knowledge'; (root/'nested').mkdir(parents=True)
    bad=root/'bad.pdf'; bad.write_bytes(b'invalid pdf')
    path=root/'nested'/'record.md'; path.write_text('---\ntitle: First\n---\nUseful fact')
    (root/'unsupported.bin').write_bytes(b'not text')
    assert okf_loader.ingest_okf_directory(root,database)==1
    status=okf_loader.get_ingestion_status(database)
    assert status['failure_count']==2
    path.write_text('---\ntitle: Second\n---\nUseful fact')
    assert okf_loader.ingest_managed_file(path,root,database)
    conn=get_connection(database)
    assert conn.execute("SELECT title FROM okf_registry WHERE doc_id='nested/record.md'").fetchone()[0]=='Second'
    real_parse=okf_loader.parse_document
    monkeypatch.setattr(okf_loader,'parse_document',lambda path: pytest.fail('Unchanged file was extracted again'))
    assert not okf_loader.ingest_document_file(path,database,doc_id='nested/record.md')
    monkeypatch.setattr(okf_loader,'parse_document',real_parse)
    path.write_text('')
    assert not okf_loader.ingest_managed_file(path,root,database)
    assert 'Useful fact' in conn.execute("SELECT content FROM fts_chunks WHERE doc_id='nested/record.md'").fetchone()[0]
    path.write_text('Fixed record')
    assert okf_loader.ingest_managed_file(path,root,database)
    assert okf_loader.get_ingestion_status(database)['failure_count']==2


def test_source_library_accepts_encoding_and_binary_formats(tmp_path, monkeypatch):
    from benchmarks.messy_fixture import make_documents
    database, _, _=setup_ingestion(tmp_path, monkeypatch)
    folder=tmp_path/'source'; make_documents(folder)
    _, admitted, _=source_library.plan_source(str(folder),'folder')
    assert {p.name for p,_ in admitted} >= {'scan.pdf','orders.xlsx','notes.txt','unicode.log'}
    storage=tmp_path/'library'
    result=source_library.add_source(str(folder/'notes.txt'),'file',db_path=database,library=storage)
    assert result['indexed_files']==1
    conn=get_connection(database)
    assert conn.execute('SELECT count(*) FROM ingestion_details').fetchone()[0]==1
    source_library.remove_source(result['id'],db_path=database,library=storage)
    assert conn.execute('SELECT count(*) FROM ingestion_details').fetchone()[0]==0


def test_watcher_processes_nested_csv_and_images(tmp_path, monkeypatch):
    from app import watcher
    knowledge=tmp_path/'knowledge'; knowledge.mkdir()
    monkeypatch.setattr(watcher,'KNOWLEDGE_DIR',knowledge)
    monkeypatch.setattr(watcher,'SKILLS_DIR',tmp_path/'skills')
    monkeypatch.setattr(watcher,'BASE_DIR',tmp_path)
    processed=[]
    monkeypatch.setattr(watcher,'ingest_managed_file',lambda path,root: processed.append(path.name) or True)
    monkeypatch.setattr(watcher,'prune_missing_knowledge',lambda root,files,identity: 0)
    watcher._STOP_EVENT.clear()
    thread=threading.Thread(target=watcher._watcher_loop,kwargs={'poll_interval':.02})
    thread.start()
    try:
        time.sleep(.1)
        (knowledge/'nested').mkdir()
        for name in ['new.csv','scan.png']:
            (knowledge/'nested'/name).write_bytes(b'changed')
        deadline=time.monotonic()+3
        while len(processed)<2 and time.monotonic()<deadline:
            time.sleep(.02)
        assert sorted(processed)==['new.csv','scan.png']
    finally:
        watcher._STOP_EVENT.set(); thread.join(3)
    assert not thread.is_alive()


def test_local_only_search_and_ingestion(tmp_path, monkeypatch):
    from app import config, zgsearch
    monkeypatch.setattr(config,'EMBEDDING_PROVIDER','openai')
    with pytest.raises(ValueError,match='local embeddings'):
        zgsearch.zg_search('query')
    path=tmp_path/'file.txt'; path.write_text('sample')
    with pytest.raises(ValueError,match='local embeddings'):
        okf_loader.ingest_document_file(path)
