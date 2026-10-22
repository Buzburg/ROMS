"""Managed-file recovery and deletion, using real SQLite and native parsing."""
import pytest

from app import okf_loader, watcher, rag_engine
from app.db import get_connection
from tests.test_ingestion_quality import setup_ingestion


def fixture(tmp_path, monkeypatch):
    database, model, _ = setup_ingestion(tmp_path, monkeypatch)
    root = tmp_path / 'knowledge'
    root.mkdir()
    path = root / 'policy.md'
    path.write_text('# Policy\n\nTTL means thirty days of retention.')
    assert okf_loader.ingest_okf_directory(root, database) == 1
    return database, model, root, path


def contents(database):
    conn = get_connection(database)
    return conn.execute('SELECT doc_id,content FROM fts_chunks ORDER BY doc_id,chunk_id').fetchall()


def test_failed_update_has_distinct_result_and_retains_index(tmp_path, monkeypatch):
    database, model, root, path = fixture(tmp_path, monkeypatch)
    assert okf_loader.ingest_managed_file(path, root, database) is False
    path.write_text('Replacement policy lasts sixty days.')
    model.values = RuntimeError('temporary failure')
    assert okf_loader.ingest_managed_file(path, root, database) is None
    assert 'thirty days' in str(contents(database))
    model.values = None
    assert okf_loader.ingest_managed_file(path, root, database) is True
    assert 'sixty days' in str(contents(database))


def test_deletion_cleans_related_rows_and_cache_but_preserves_imports(tmp_path, monkeypatch):
    database, _, root, path = fixture(tmp_path, monkeypatch)
    imported = root / 'snapshot.md'
    imported.write_text('# Import\n\nSaved independent evidence.')
    okf_loader.ingest_document_file(imported, database, doc_id='import:retained')
    imported.unlink()
    conn = get_connection(database)
    old_ids = [row[0] for row in conn.execute("SELECT chunk_id FROM fts_chunks WHERE doc_id='policy.md'")]
    # Failure diagnostics for an indexed document must disappear with its index.
    okf_loader._failure_table(conn)
    conn.execute('INSERT INTO ingestion_failures(source_path,error) VALUES (?,?)', (str(path), 'old failure'))
    conn.commit()
    cleared = []
    monkeypatch.setattr(rag_engine, 'clear_result_cache', lambda: cleared.append(True))
    path.unlink()
    assert okf_loader.ingest_okf_directory(root, database) == 0
    for table in ('okf_registry', 'vec_chunks', 'fts_chunks', 'ingestion_details', 'knowledge_navigation'):
        assert conn.execute(f'SELECT count(*) FROM {table} WHERE doc_id=?', ('policy.md',)).fetchone()[0] == 0
    for chunk in old_ids:
        assert conn.execute('SELECT count(*) FROM chunk_topics WHERE chunk_id=?', (chunk,)).fetchone()[0] == 0
    assert conn.execute('SELECT count(*) FROM ingestion_failures').fetchone()[0] == 0
    assert all(count == actual for count, actual in conn.execute('SELECT t.chunk_count,count(ct.chunk_id) FROM topics t LEFT JOIN chunk_topics ct USING(topic_id) GROUP BY t.topic_id'))
    assert {row[0] for row in contents(database)} == {'import:retained'}
    assert cleared == [True]


def test_rename_removes_old_identity(tmp_path, monkeypatch):
    database, _, root, path = fixture(tmp_path, monkeypatch)
    path.rename(root / 'renamed.md')
    assert okf_loader.ingest_okf_directory(root, database) == 1
    assert {row[0] for row in contents(database)} == {'renamed.md'}


def test_unavailable_root_is_not_recreated_or_pruned(tmp_path, monkeypatch):
    database, _, root, path = fixture(tmp_path, monkeypatch)
    root.rename(tmp_path / 'temporarily-unmounted')
    assert okf_loader.ingest_okf_directory(root, database) == 0
    assert not root.exists()
    assert 'thirty days' in str(contents(database))


def test_incomplete_walk_cannot_prune(tmp_path, monkeypatch):
    database, _, root, path = fixture(tmp_path, monkeypatch)
    path.unlink()
    def failed_walk(*args, onerror, **kwargs):
        yield str(root), [], []
        onerror(PermissionError('unreadable child'))
    monkeypatch.setattr(okf_loader.os, 'walk', failed_walk)
    with pytest.raises(PermissionError):
        okf_loader.ingest_okf_directory(root, database)
    assert 'thirty days' in str(contents(database))


def test_root_disappears_after_scan_preserves_index(tmp_path, monkeypatch):
    database, _, root, path = fixture(tmp_path, monkeypatch)
    path.unlink()
    files, identity = okf_loader.scan_knowledge_files(root)
    root.rmdir()
    with pytest.raises(FileNotFoundError):
        okf_loader.prune_missing_knowledge(root, files, identity, database)
    assert 'thirty days' in str(contents(database))


def test_reappeared_file_and_other_roots_are_preserved(tmp_path, monkeypatch):
    database, _, root, path = fixture(tmp_path, monkeypatch)
    other = tmp_path / 'other'
    other.mkdir()
    other_path = other / 'other.md'
    other_path.write_text('Other root evidence')
    okf_loader.ingest_okf_directory(other, database)
    other_path.unlink()
    path.unlink()
    files, identity = okf_loader.scan_knowledge_files(root)
    path.write_text('Reappeared before reconciliation')
    assert okf_loader.prune_missing_knowledge(root, files, identity, database) == 0
    assert {row[0] for row in contents(database)} == {'policy.md', 'other.md'}


def test_cleanup_rolls_back_all_tables_on_error(tmp_path, monkeypatch):
    database, _, root, path = fixture(tmp_path, monkeypatch)
    conn = get_connection(database)
    conn.execute("CREATE TRIGGER prevent_delete BEFORE DELETE ON okf_registry BEGIN SELECT RAISE(ABORT, 'simulated write failure'); END")
    conn.commit()
    path.unlink()
    with pytest.raises(Exception, match='simulated write failure'):
        okf_loader.ingest_okf_directory(root, database)
    for table in ('okf_registry', 'vec_chunks', 'fts_chunks', 'ingestion_details', 'knowledge_navigation'):
        assert conn.execute(f'SELECT count(*) FROM {table} WHERE doc_id=?', ('policy.md',)).fetchone()[0] > 0


class Clock:
    def __init__(self, callback, stop_after):
        self.now = 0
        self.polls = 0
        self.stopped = False
        self.callback = callback
        self.stop_after = stop_after

    def is_set(self):
        return self.stopped

    def wait(self, seconds):
        self.now += seconds
        if seconds == .25:
            self.polls += 1
            self.callback(self.polls)
            self.stopped = self.polls >= self.stop_after
        return self.stopped


def run_watcher(tmp_path, monkeypatch, database, root, callback, stop_after=20):
    clock = Clock(callback, stop_after)
    monkeypatch.setattr(watcher, '_STOP_EVENT', clock)
    monkeypatch.setattr(watcher.time, 'monotonic', lambda: clock.now)
    monkeypatch.setattr(watcher, 'KNOWLEDGE_DIR', root)
    monkeypatch.setattr(watcher, 'SKILLS_DIR', tmp_path / 'skills')
    monkeypatch.setattr(watcher, 'BASE_DIR', tmp_path)
    actual_ingest = okf_loader.ingest_managed_file
    attempts = []
    def ingest(path, base):
        attempts.append(clock.now)
        return actual_ingest(path, base, database)
    monkeypatch.setattr(watcher, 'ingest_managed_file', ingest)
    actual_prune = okf_loader.prune_missing_knowledge
    monkeypatch.setattr(watcher, 'prune_missing_knowledge', lambda base, files, identity: actual_prune(base, files, identity, database))
    watcher._watcher_loop(poll_interval=.25)
    return attempts


def test_watcher_retries_failed_startup_without_another_edit(tmp_path, monkeypatch):
    database, model, root, path = fixture(tmp_path, monkeypatch)
    path.write_text('Replacement policy lasts sixty days.')
    model.values = RuntimeError('temporarily unavailable')
    def tick(poll):
        if poll == 3:
            model.values = None
    attempts = run_watcher(tmp_path, monkeypatch, database, root, tick)
    assert len(attempts) == 2
    assert attempts[1] - attempts[0] >= 1
    assert 'sixty days' in str(contents(database))
    assert okf_loader.get_ingestion_status(database)['failure_count'] == 0


def test_watcher_permanent_failure_backs_off(tmp_path, monkeypatch):
    database, model, root, path = fixture(tmp_path, monkeypatch)
    path.write_text('Changed policy')
    model.values = RuntimeError('persistent error')
    attempts = run_watcher(tmp_path, monkeypatch, database, root, lambda _: None, stop_after=600)
    assert len(attempts) == 8
    assert all(right-left >= delay for left, right, delay in zip(attempts, attempts[1:], [1, 2, 4, 8, 16, 32, 60]))
    assert 'thirty days' in str(contents(database))


def test_watcher_edit_bypasses_retry_delay_and_deletion_reconciles(tmp_path, monkeypatch):
    database, model, root, path = fixture(tmp_path, monkeypatch)
    path.write_text('First failing edit')
    model.values = RuntimeError('failure')
    def tick(poll):
        if poll == 3:
            model.values = None
            path.write_text('A newer edit succeeds immediately.')
        elif poll == 5:
            assert 'newer edit' in str(contents(database))
            path.unlink()
    attempts = run_watcher(tmp_path, monkeypatch, database, root, tick, stop_after=8)
    assert len(attempts) == 2
    assert attempts[1] - attempts[0] < 1
    assert contents(database) == []


def test_replaced_root_identity_cannot_prune(tmp_path, monkeypatch):
    database, _, root, path = fixture(tmp_path, monkeypatch)
    path.unlink()
    files, identity = okf_loader.scan_knowledge_files(root)
    root.rename(tmp_path / 'old-root')
    root.mkdir()
    with pytest.raises(OSError, match='root changed'):
        okf_loader.prune_missing_knowledge(root, files, identity, database)
    assert 'thirty days' in str(contents(database))


def test_watcher_notices_edit_during_embedding(tmp_path, monkeypatch):
    database, model, root, path = fixture(tmp_path, monkeypatch)
    path.write_text('First replacement policy.')
    encode = model.encode
    calls = []
    def changing_encode(*args, **kwargs):
        result = encode(*args, **kwargs)
        calls.append(True)
        if len(calls) == 1:
            path.write_text('Newer content written during embedding.')
        return result
    monkeypatch.setattr(model, 'encode', changing_encode)
    attempts = run_watcher(tmp_path, monkeypatch, database, root, lambda _: None, stop_after=8)
    assert len(attempts) == 2
    assert 'Newer content' in str(contents(database))


def test_deletion_invalidates_real_search_results(tmp_path, monkeypatch):
    database, _, root, path = fixture(tmp_path, monkeypatch)
    from app import zgsearch
    import numpy as np
    monkeypatch.setattr(rag_engine, '_get_query_embedding', lambda *args, **kwargs: np.ones(768, dtype=np.float32).tobytes())
    assert zgsearch.zg_search('retention', db_path=database)
    assert zgsearch.zg_search('retention', db_path=database)
    path.unlink()
    okf_loader.ingest_okf_directory(root, database)
    assert zgsearch.zg_search('retention', db_path=database) == []


def test_deleted_failed_first_import_clears_diagnostic(tmp_path, monkeypatch):
    database, _, root, _ = fixture(tmp_path, monkeypatch)
    path = root / 'unsupported.bin'
    path.write_bytes(b'unsupported')
    assert okf_loader.ingest_managed_file(path, root, database) is None
    assert okf_loader.get_ingestion_status(database)['failure_count'] == 1
    path.unlink()
    okf_loader.ingest_okf_directory(root, database)
    assert okf_loader.get_ingestion_status(database)['failure_count'] == 0
