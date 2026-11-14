"""Locations survive splitting, indexing, replacement and bounded expansion."""
import json

import pytest

from app import document_parse, okf_loader
from app.db import get_connection
from app.source_context import expand, locations
from test_ingestion_quality import setup_ingestion


def test_markdown_paths_offsets_and_fenced_headings(tmp_path):
    path = tmp_path / 'guide.md'
    path.write_text('# Deployment\n\n' + ('Keep the violet setting. ' * 90) +
                    '\n\n```python\n# not a section\n```\n## Recovery\nRestore the amber backup.')
    parsed = document_parse.parse_document(path)
    assert len(parsed.chunks) > 4
    for content, source in zip(parsed.chunks, parsed.chunk_metadata):
        assert parsed.text[source['start_char']:source['end_char']] == content
        assert source['offset_basis'] == 'normalized_text'
        assert 'not a section' not in source['section_path']
    assert parsed.chunk_metadata[-1]['section_path'] == ['Deployment', 'Recovery']
    assert parsed.chunk_metadata[1]['section_path'] == ['Deployment']


def test_python_symbols_and_locations(tmp_path):
    path = tmp_path / 'worker.py'
    path.write_text('import sys\n\n@decorator\ndef recover():\n    """Restore state."""\n    return 1\n\nclass Manager:\n    pass\n')
    parsed = document_parse.parse_document(path)
    found = {meta.get('symbol'): (text, meta) for text, meta in zip(parsed.chunks, parsed.chunk_metadata)}
    assert '@decorator' in found['recover'][0]
    assert found['recover'][1]['line_start'] == 3
    assert found['Manager'][1]['line_start'] == 8


def test_metadata_and_embedding_context_are_distinct_and_atomic(tmp_path, monkeypatch):
    database, model, _ = setup_ingestion(tmp_path, monkeypatch)
    path = tmp_path / 'manual.md'
    path.write_text('# Pumps\n\n' + ('Amber replacement procedure. ' * 100) + '\n\n# Motors\nOther evidence.')
    assert okf_loader.ingest_document_file(path, database)
    conn = get_connection(database)
    indexed = conn.execute('SELECT chunk_id,content FROM fts_chunks ORDER BY chunk_id').fetchall()
    meta = locations(conn, [cid for cid, _ in indexed])
    assert len(meta) == len(indexed)
    assert model.calls[0][0][1].startswith('Document: manual.md\nSection: Pumps\n\n')
    assert not indexed[1][1].startswith('Document:')
    selected = indexed[1][0]
    result = expand(selected, neighbors=3, db_path=database)
    assert any(item['chunk_id'] == selected for item in result['sources'])
    assert all(item['source']['section_path'] == ['Pumps'] for item in result['sources'])
    assert result['source_characters'] == sum(len(item['content']) for item in result['sources'])
    with pytest.raises(ValueError, match='nothing was clipped'):
        expand(selected, max_chars=1, db_path=database)
    old_meta = conn.execute('SELECT * FROM chunk_sources').fetchall()
    path.write_text('# Changed\nReplacement')
    model.values = ValueError('embedding failed')
    with pytest.raises(ValueError, match='embedding failed'):
        okf_loader.ingest_document_file(path, database)
    assert conn.execute('SELECT * FROM chunk_sources').fetchall() == old_meta
    model.values = None
    assert okf_loader.ingest_document_file(path, database)
    assert all(json.loads(row[0])['section_path'] == ['Changed'] for row in
               conn.execute('SELECT metadata_json FROM chunk_sources'))
    assert conn.execute('SELECT count(*) FROM chunk_sources').fetchone()[0] == conn.execute('SELECT count(*) FROM fts_chunks').fetchone()[0]


def test_legacy_index_does_not_invent_locations(tmp_path):
    from app.db import init_database
    database = tmp_path / 'legacy.db'
    init_database(database)
    conn = get_connection(database)
    conn.execute('DROP TABLE chunk_sources')
    conn.execute("INSERT INTO fts_chunks VALUES (1,'legacy.md','Known original')")
    conn.commit()
    result = expand(1, db_path=database)
    assert result['sources'] == [dict(chunk_id=1, doc_id='legacy.md', content='Known original', source={})]


def test_real_binary_extraction_locations(tmp_path):
    from benchmarks.messy_fixture import make_documents
    make_documents(tmp_path)
    for name, field, value in [('inspection.pdf', 'page', 1), ('safety.pptx', 'slide', 1), ('orders.xlsx', 'sheet', 'Orders')]:
        parsed = document_parse.parse_document(tmp_path / name)
        assert parsed.chunk_metadata and all(meta[field] == value for meta in parsed.chunk_metadata)


def test_table_columns_survive_long_cell_split(tmp_path):
    path = tmp_path / 'inventory.csv'
    path.write_text('Product,Instructions\nPump,' + 'Keep the valve open. ' * 100)
    parsed = document_parse.parse_document(path)
    assert len(parsed.chunks) > 2
    assert all(meta['columns'] == ['Product', 'Instructions'] for meta in parsed.chunk_metadata)


def test_ocr_languages_are_forwarded_without_shell_interpretation(monkeypatch):
    from app import document_extract
    from PIL import Image
    calls = []
    monkeypatch.setenv('ROMS_OCR_LANGUAGES', 'eng+deu')
    monkeypatch.setattr(document_extract.shutil, 'which', lambda _: '/test/tesseract')
    monkeypatch.setattr(document_extract, '_run', lambda command, *a, **k: calls.append(command) or b'Beleg')
    assert document_extract._ocr(Image.new('RGB', (10, 10)), 0) == 'Beleg'
    assert calls[0][-2:] == ['-l', 'eng+deu']
    monkeypatch.setenv('ROMS_OCR_LANGUAGES', 'eng; command')
    with pytest.raises(ValueError, match='language names'):
        document_extract.ocr_language()


def test_quoted_table_headers_are_not_split_into_invented_columns(tmp_path):
    path = tmp_path / 'names.csv'
    path.write_text('"First, Last",Role\n"Ada, Lovelace",Engineer\n')
    parsed = document_parse.parse_document(path)
    assert parsed.chunk_metadata[0]['columns'] == ['First, Last', 'Role']


def test_search_cache_protects_nested_locations(tmp_path, monkeypatch):
    from app import rag_engine
    database, _, _ = setup_ingestion(tmp_path, monkeypatch)
    path = tmp_path / 'guide.md'
    path.write_text('# Violet pump\n\nTurn the amber lever to stop the pump.')
    okf_loader.ingest_document_file(path, database)
    monkeypatch.setattr(rag_engine, 'compute_embedding_vector', lambda _: [1.] * 768)
    results = rag_engine.local_search('violet pump', db_path=database)
    assert results[0]['source']['section_path'] == ['Violet pump']
    results[0]['source']['section_path'].append('caller change')
    assert 'caller change' not in rag_engine.local_search('violet pump', db_path=database)[0]['source']['section_path']


def test_removed_documents_leave_no_location_records(tmp_path, monkeypatch):
    database, _, _ = setup_ingestion(tmp_path, monkeypatch)
    root = tmp_path / 'knowledge'
    root.mkdir()
    path = root / 'guide.md'
    path.write_text('# Evidence\n\nExact source')
    assert okf_loader.ingest_okf_directory(root, database) == 1
    path.unlink()
    okf_loader.ingest_okf_directory(root, database)
    conn = get_connection(database)
    assert conn.execute('SELECT count(*) FROM chunk_sources').fetchone()[0] == 0


def test_upload_embedding_uses_original_display_name(tmp_path, monkeypatch):
    database, model, _ = setup_ingestion(tmp_path, monkeypatch)
    snapshot = tmp_path / 'opaque-upload-id.md'
    snapshot.write_text('Use the amber lever.')
    assert okf_loader.ingest_document_file(snapshot, database, doc_id='import:opaque', display_name='Pump manual.md')
    assert model.calls[0][0][0].startswith('Document: Pump manual.md\n\n')
    assert 'opaque-upload-id' not in model.calls[0][0][0]
