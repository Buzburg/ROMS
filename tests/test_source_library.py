"""Exercise real repository admission and namespaced indexing on Linux."""
import os
from pathlib import Path
import subprocess

import pytest

from app import source_library as library
from app.db import get_connection
from test_ingestion_quality import setup_ingestion

pytestmark = pytest.mark.skipif(os.name != 'posix', reason='Descriptor confinement requires Linux')


def make_repo(path: Path) -> Path:
    path.mkdir()
    subprocess.run(['git', 'init', '-q', str(path)], check=True)
    return path


def stage(repo: Path) -> None:
    subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)


def test_repo_skips_secrets_symlinks_untracked_and_never_executes(tmp_path):
    repo = make_repo(tmp_path / 'repo')
    (repo / 'README.md').write_text('Ordinary readable repository documentation.')
    (repo / '.env.secret').write_text('private-token')
    (repo / '.ENV.txt').write_text('private-token')
    (repo / 'credentials.json').write_text('{"password":"private"}')
    (repo / 'private.txt').write_text('-----BEGIN OPENSSH PRIVATE KEY-----')
    (repo / 'model.gguf').write_bytes(b'GGUF')
    (repo / 'script.py').write_text('raise RuntimeError("do not run imported code")')
    outside = tmp_path / 'outside.md'
    outside.write_text('This outside content must not enter the source snapshot.')
    (repo / 'link.md').symlink_to(outside)
    stage(repo)
    (repo / 'untracked.md').write_text('Not part of the tracked repository snapshot.')
    _, admitted, skipped = library.plan_source(str(repo), 'repo')
    assert {str(path) for path, _ in admitted} == {'README.md', 'script.py'}
    assert {'link.md', '.env.secret', 'private.txt', 'credentials.json', 'model.gguf'} <= {item['path'] for item in skipped}


def test_snapshot_index_and_removal_preserve_originals_and_other_sources(tmp_path, monkeypatch):
    database, _, _ = setup_ingestion(tmp_path, monkeypatch)
    storage = tmp_path / 'library'
    sources = []
    for name in ('alpha', 'beta'):
        repo = make_repo(tmp_path / name)
        (repo / 'README.md').write_text(name + ' repository uses the violet deployment protocol.')
        stage(repo)
        sources.append(library.add_source(str(repo), 'repo', db_path=database, library=storage))
    conn = get_connection(database)
    assert conn.execute('SELECT COUNT(*) FROM okf_registry').fetchone()[0] == 2
    first = sources[0]
    original = tmp_path / 'alpha/README.md'
    original.write_text('User edits made after import stay independent of the snapshot.')
    snapshot = storage / first['id'] / 'files/README.md'
    assert snapshot.read_text().startswith('alpha repository')
    library.remove_source(first['id'], db_path=database, library=storage)
    assert original.read_text().startswith('User edits')
    assert conn.execute('SELECT COUNT(*) FROM okf_registry').fetchone()[0] == 1
    assert conn.execute('SELECT COUNT(*) FROM vec_chunks').fetchone()[0] == 1
    assert len(library.list_sources(storage)) == 1
    assert conn.execute('SELECT doc_id FROM okf_registry').fetchone()[0].startswith('source:' + sources[1]['id'])
    assert all(count == actual for count, actual in conn.execute(
        'SELECT t.chunk_count, count(ct.chunk_id) FROM topics t '
        'LEFT JOIN chunk_topics ct USING(topic_id) GROUP BY t.topic_id'))


def test_failed_import_rolls_back_its_index_only(tmp_path, monkeypatch):
    database, _, _ = setup_ingestion(tmp_path, monkeypatch)
    storage = tmp_path / 'library'
    folder = tmp_path / 'folder'
    folder.mkdir()
    for name in ('a.md', 'b.md'):
        (folder / name).write_text('Known searchable content for ' + name)
    real_ingest = library.ingest_document_file
    count = 0
    def fail_second(*args, **kwargs):
        nonlocal count
        count += 1
        if count == 2:
            raise RuntimeError('injected embedding failure')
        return real_ingest(*args, **kwargs)
    monkeypatch.setattr(library, 'ingest_document_file', fail_second)
    with pytest.raises(RuntimeError, match='injected'):
        library.add_source(str(folder), 'folder', db_path=database, library=storage)
    assert get_connection(database).execute('SELECT COUNT(*) FROM okf_registry').fetchone()[0] == 0
    assert get_connection(database).execute('SELECT COUNT(*) FROM vec_chunks').fetchone()[0] == 0
    assert library.list_sources(storage)[0]['status'] == 'failed'


def test_directory_symlink_and_limits_fail_closed(tmp_path, monkeypatch):
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'guide.md').write_text('External directory content must be excluded.')
    root = tmp_path / 'root'
    root.mkdir()
    (root / 'link').symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match='No supported'):
        library.plan_source(str(root), 'folder')
    with pytest.raises(OSError):
        library._read_regular(root, Path('link/guide.md'))
    (root / 'guide.md').write_text('This document is bigger than the test limit.')
    monkeypatch.setattr(library, 'MAX_FILE_BYTES', 8)
    with pytest.raises(ValueError, match='No supported'):
        library.plan_source(str(root), 'folder')


def test_preview_remove_cannot_delete(tmp_path, monkeypatch):
    monkeypatch.setattr('sys.argv', ['source_library', 'remove', '0' * 32, '--preview'])
    monkeypatch.setattr(library, 'remove_source', lambda *args: pytest.fail('preview must never remove'))
    with pytest.raises(SystemExit) as error:
        library.main()
    assert error.value.code == 2


def test_menu_cancel_does_not_import(tmp_path, monkeypatch, capsys):
    source = tmp_path / 'guide.md'
    source.write_text('Previewable local document with sufficient content.')
    answers = iter(['1', str(source), 'no', '0'])
    monkeypatch.setattr('builtins.input', lambda _: next(answers))
    monkeypatch.setattr(library, 'add_source', lambda *args: pytest.fail('Cancelled import must not run'))
    library.library_menu()
    assert '1 files' in capsys.readouterr().out


def test_repository_manifest_limit(tmp_path, monkeypatch):
    repo = make_repo(tmp_path / 'repo')
    (repo / 'README.md').write_text('Readable repository text.')
    stage(repo)
    monkeypatch.setattr(library, 'MAX_MANIFEST_BYTES', 4)
    with pytest.raises(ValueError, match='manifest too large'):
        library.plan_source(str(repo), 'repo')
