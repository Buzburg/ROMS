"""Durable intake acceptance: real native parsing, stubbed embeddings, actual SQLite and HTTP."""
from starlette.testclient import TestClient
from app.knowledge_intake import Intake
from app.knowledge_catalog import catalog
from app.knowledge_web import create_app
from tests.test_ingestion_quality import setup_ingestion
import pytest


def queue(tmp_path, monkeypatch):
    db, model, _ = setup_ingestion(tmp_path, monkeypatch)
    return Intake(db, tmp_path / 'originals'), model


def test_restart_resume_and_source_navigation(tmp_path, monkeypatch):
    intake, model = queue(tmp_path, monkeypatch)
    body = b'# Retention\n\nTTL means time to live.\n\nNo invented definitions here.'
    job = intake.submit('folder/Policy.md', body)
    with intake.connection() as conn:
        conn.execute("UPDATE import_jobs SET state='processing' WHERE id=?", (job,))
    restarted = Intake(intake.db_path, intake.storage)
    with restarted.worker_lock() as acquired:
        assert acquired
        restarted.recover()
        assert restarted.process_one()
        assert not restarted.process_one()
    assert restarted.status()['counts'] == {'ready': 1}
    data = catalog(intake.db_path)['documents'][0]
    assert data['title'] == 'folder/Policy.md'
    assert [(n['kind'], n['label']) for n in data['navigation']] == [('section', 'Retention'), ('definition', 'TTL')]
    assert data['navigation'][1]['detail'] == 'time to live.'
    assert list(intake.storage.iterdir())[0].read_bytes() == body
    # Crash between index commit and job acknowledgment must not duplicate chunks.
    with intake.connection() as conn:
        conn.execute("UPDATE import_jobs SET state='processing'")
        before = conn.execute('SELECT count(*) FROM fts_chunks').fetchone()[0]
    with restarted.worker_lock():
        restarted.recover()
        restarted.process_one()
    with intake.connection() as conn:
        assert conn.execute('SELECT count(*) FROM fts_chunks').fetchone()[0] == before
    assert len(model.calls) == 1


def test_failures_retry_and_exclusive_worker(tmp_path, monkeypatch):
    intake, model = queue(tmp_path, monkeypatch)
    first = intake.submit('Bad.md', b'Original text')
    intake.submit('Good.md', b'Good text')
    with intake.worker_lock() as held:
        assert held
        with Intake(intake.db_path, intake.storage).worker_lock() as other:
            assert not other
        model.values = RuntimeError('model unavailable')
        intake.process_one()
        model.values = None
        intake.process_one()
        assert intake.status()['counts'] == {'failed': 1, 'ready': 1}
        assert intake.retry(first)
        assert not intake.retry(first)
        intake.process_one()
    assert intake.status()['counts'] == {'ready': 2}


@pytest.mark.parametrize('name', ['../x.md', '/x.md', 'x/../../x.md', '.env.txt', 'x/.hidden.md', 'x\\y.md', 'run.exe', 'id_rsa'])
def test_reject_paths_and_unsupported_files(tmp_path, monkeypatch, name):
    intake, _ = queue(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        intake.submit(name, b'content')
    assert not list(intake.storage.iterdir())


def test_http_auth_origin_upload_and_source(tmp_path, monkeypatch):
    intake, _ = queue(tmp_path, monkeypatch)
    app = create_app(intake, 'secret-token', start_worker=False)
    with TestClient(app, base_url='http://127.0.0.1:8845') as client:
        assert client.get('/').status_code == 200
        assert client.get('/api/jobs').status_code == 401
        headers = {'X-ROMS-Token': 'secret-token'}
        assert client.post('/api/upload?name=x.md', content=b'a', headers={**headers, 'Origin': 'http://evil.example'}).status_code == 403
        assert client.get('/api/jobs', headers={**headers, 'Host': 'evil.example'}).status_code == 403
        result = client.post('/api/upload?name=Guide.md', content=b'# Guide\n\nTTL means time to live.', headers=headers)
        assert result.status_code == 202
        with intake.worker_lock():
            intake.process_one()
        data = client.get('/api/catalog', headers=headers).json()
        assert data['total'] == 1
        chunk = data['documents'][0]['navigation'][0]['chunk_id']
        assert '# Guide' in client.get(f'/api/source/{chunk}', headers=headers).json()['content']
        assert client.get('/api/jobs?offset=bad', headers=headers).status_code == 400
        assert client.get('/api/jobs', headers=headers).json()['counts'] == {'ready': 1}


def test_navigation_replaced_and_deleted_sources_hidden(tmp_path, monkeypatch):
    from app.okf_loader import ingest_document_file
    intake, _ = queue(tmp_path, monkeypatch)
    path = tmp_path / 'Updated.md'
    path.write_text('# Old\n\nTTL means old value.')
    ingest_document_file(path, intake.db_path)
    path.write_text('# New\n\nPlain prose without definitions.')
    ingest_document_file(path, intake.db_path)
    nav = catalog(intake.db_path)['documents'][0]['navigation']
    assert [n['label'] for n in nav] == ['New']
    with intake.connection() as conn:
        conn.execute('DELETE FROM fts_chunks')
    assert catalog(intake.db_path)['documents'][0]['navigation'] == []


def test_http_and_queue_size_limits(tmp_path, monkeypatch):
    import app.knowledge_web as web
    import app.knowledge_intake as module
    intake, _ = queue(tmp_path, monkeypatch)
    monkeypatch.setattr(web, 'MAX_FILE_BYTES', 8)
    monkeypatch.setattr(module, 'MAX_FILE_BYTES', 8)
    with pytest.raises(ValueError):
        intake.submit('TooBig.md', b'123456789')
    with TestClient(create_app(intake, 'secret', start_worker=False), base_url='http://127.0.0.1:8845') as client:
        assert client.post('/api/upload?name=x.md', content=b'123456789', headers={'X-ROMS-Token':'secret'}).status_code == 413
    assert intake.status()['counts'] == {}
