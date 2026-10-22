"""Local source snapshots and namespaced indexing; imported code is never run."""
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import stat
import subprocess
import time
import uuid

from app.config import DATA_DIR
from app.db import get_connection, init_database
from app.okf_loader import SUPPORTED_EXTENSIONS, ingest_document_file

MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_FILES = 1000
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
SKIP_DIRS = {'.git', '.hg', '.svn', '.pixi', '.venv', 'venv', 'node_modules',
             '__pycache__', '.pytest_cache', 'target', 'dist', 'build', '.aws', '.ssh', '.codex', '.agents'}
SECRET_NAMES = {'credentials.json', 'secrets.json', 'secrets.yaml', 'secrets.yml',
                'id_rsa', 'id_ed25519', '.npmrc', '.pypirc', 'runtime.env'}


def local_path(value: str) -> Path:
    if os.name != 'nt' and re.match(r'^[A-Za-z]:[\\/]', value):
        value = '/mnt/' + value[0].lower() + '/' + value[3:].replace('\\', '/')
    return Path(value).expanduser().resolve(strict=True)


def _admitted(relative: Path) -> bool:
    name = relative.name.lower()
    return (not any(part.lower() in SKIP_DIRS for part in relative.parts)
            and not any(part.lower().startswith('.env') for part in relative.parts)
            and name not in SECRET_NAMES
            and relative.suffix.lower() in SUPPORTED_EXTENSIONS)


def _read_regular(root: Path, relative: Path) -> bytes:
    """Pin each directory on Linux; never follow a repository's symlink."""
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('Invalid source path')
    if os.name != 'posix':
        raise RuntimeError('Source intake runs inside Linux/WSL')
    else:
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for component in relative.parts[:-1]:
                child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                os.close(directory)
                directory = child
            fd = os.open(relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        finally:
            os.close(directory)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE_BYTES:
            raise ValueError('Source is not a bounded regular file')
        content = stream.read(MAX_FILE_BYTES + 1)
        if len(content) > MAX_FILE_BYTES:
            raise ValueError('Oversized source')
        # Decoding and binary format validation belong to the shared importer.
        if not content.strip():
            raise ValueError('Empty source')
        if re.search(br'-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----', content):
            raise ValueError('Private-key content rejected')
        return content


def _git_manifest(root: Path) -> bytes:
    env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
    command = ['git', '-c', 'core.fsmonitor=false', '-c', 'core.hooksPath=/dev/null',
               '-C', str(root), 'ls-files', '-z', '--cached']
    process = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 15
    output = bytearray()
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise subprocess.TimeoutExpired(command, 15)
                block = os.read(process.stdout.fileno(), 65536)
                if not block:
                    break
                output.extend(block)
                if len(output) > MAX_MANIFEST_BYTES:
                    raise ValueError('Repository manifest too large')
        if process.wait(timeout=max(0, deadline - time.monotonic())):
            raise RuntimeError('Cannot list tracked repository files; check repository ownership and access')
        return bytes(output)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdout.close()


def plan_source(value: str, kind: str) -> tuple[Path, list[tuple[Path, bytes]], list[dict[str, str]]]:
    root = local_path(value)
    if kind == 'file':
        candidates = [Path(root.name)]
        root = root.parent
    elif kind == 'repo':
        if not root.is_dir() or not (root / '.git').exists():
            raise ValueError('Expected a local Git repository; use folder for an extracted archive')
        candidates = [Path(os.fsdecode(name)) for name in _git_manifest(root).split(b'\x00') if name]
    elif kind == 'folder':
        if not root.is_dir():
            raise ValueError('Expected a folder')
        candidates = []
        visited = 0
        for directory, folders, filenames in os.walk(root, followlinks=False):
            folders[:] = sorted(name for name in folders if name.lower() not in SKIP_DIRS
                                and not name.lower().startswith('.env')
                                and not (Path(directory) / name).is_symlink())
            visited += len(folders) + len(filenames)
            if visited > 20000:
                raise ValueError('Folder scan exceeds 20,000 entries; select a smaller folder')
            candidates.extend((Path(directory) / name).relative_to(root) for name in sorted(filenames))
    else:
        raise ValueError('Source kind must be file, repo or folder')
    admitted, skipped = [], []
    total = 0
    for relative in sorted(set(candidates)):
        if not _admitted(relative):
            skipped.append({'path': relative.as_posix(), 'reason': 'excluded name or unsupported format'})
            continue
        if len(admitted) >= MAX_FILES:
            raise ValueError('Source exceeds 1,000 eligible files; select a smaller folder')
        try:
            content = _read_regular(root, relative)
        except (OSError, ValueError) as error:
            skipped.append({'path': relative.as_posix(), 'reason': str(error)})
            continue
        total += len(content)
        if total > MAX_TOTAL_BYTES:
            raise ValueError('Source exceeds 32 MiB; select a smaller folder')
        admitted.append((relative, content))
    if not admitted:
        raise ValueError('No supported, readable files were selected')
    return root, admitted, skipped


def _manifest_path(source_id: str, library: Path) -> Path:
    if not re.fullmatch(r'[a-f0-9]{32}', source_id):
        raise ValueError('Invalid source ID')
    return library / source_id / 'manifest.json'


def _write_manifest(path: Path, manifest: dict) -> None:
    temporary = path.with_suffix('.new')
    temporary.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    temporary.replace(path)


def list_sources(library: Path | None = None) -> list[dict]:
    library = library or DATA_DIR / 'library'
    return [json.loads(path.read_text()) for path in sorted(library.glob('*/manifest.json'))]


def add_source(value: str, kind: str, *, db_path: Path | None = None, library: Path | None = None) -> dict:
    _, files, skipped = plan_source(value, kind)
    library = library or DATA_DIR / 'library'
    source_id = uuid.uuid4().hex
    manifest_path = _manifest_path(source_id, library)
    manifest_path.parent.mkdir(parents=True, mode=0o700)
    manifest = {'id': source_id, 'kind': kind, 'origin': str(local_path(value)),
                'status': 'indexing', 'files': [], 'skipped': skipped}
    _write_manifest(manifest_path, manifest)
    try:
        for relative, content in files:
            snapshot = manifest_path.parent / 'files' / relative
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            snapshot.write_bytes(content)
            manifest['files'].append({'path': relative.as_posix(), 'bytes': len(content),
                                      'sha256': hashlib.sha256(content).hexdigest(),
                                      'doc_id': f'source:{source_id}/{relative.as_posix()}'})
        _write_manifest(manifest_path, manifest)
        init_database(db_path)
        for item in manifest['files']:
            snapshot = manifest_path.parent / 'files' / item['path']
            item['indexed'] = ingest_document_file(snapshot, db_path, doc_id=item['doc_id'])
        manifest['indexed_files'] = sum(item['indexed'] for item in manifest['files'])
        if not manifest['indexed_files']:
            raise ValueError('No indexable document content was found')
        manifest['status'] = 'ready'
    except Exception as error:
        manifest['status'] = 'failed'
        manifest['error'] = type(error).__name__ + ': ' + str(error)
        _write_manifest(manifest_path, manifest)
        try:
            remove_source(source_id, db_path=db_path, library=library, keep_snapshot=True)
        except Exception as cleanup_error:
            manifest['status'] = 'cleanup_required'
            manifest['cleanup_error'] = str(cleanup_error)
            _write_manifest(manifest_path, manifest)
        raise
    _write_manifest(manifest_path, manifest)
    return manifest


def remove_source(source_id: str, *, db_path: Path | None = None, library: Path | None = None,
                  keep_snapshot: bool = False) -> None:
    library = library or DATA_DIR / 'library'
    path = _manifest_path(source_id, library)
    if not path.is_file():
        raise ValueError('Source not found')
    if not keep_snapshot:
        manifest = json.loads(path.read_text())
        manifest['status'] = 'removing'
        _write_manifest(path, manifest)
    connection = get_connection(db_path, reuse=False)
    try:
        with connection:
            ids = [row[0] for row in connection.execute('SELECT doc_id FROM okf_registry WHERE doc_id LIKE ?',
                                                        (f'source:{source_id}/%',))]
            has_details = connection.execute("SELECT 1 FROM sqlite_master WHERE name='ingestion_details'").fetchone()
            for doc_id in ids:
                if has_details:
                    connection.execute('DELETE FROM ingestion_details WHERE doc_id=?', (doc_id,))
                connection.execute('DELETE FROM chunk_topics WHERE chunk_id IN (SELECT chunk_id FROM fts_chunks WHERE doc_id=?)', (doc_id,))
                if connection.execute("SELECT 1 FROM sqlite_master WHERE name='knowledge_skill_sources'").fetchone():
                    connection.execute('DELETE FROM knowledge_skill_sources WHERE doc_id=?', (doc_id,))
                for table in ('vec_chunks', 'fts_chunks', 'okf_registry'):
                    connection.execute(f'DELETE FROM {table} WHERE doc_id=?', (doc_id,))
            connection.execute('UPDATE topics SET chunk_count=(SELECT COUNT(*) FROM chunk_topics WHERE chunk_topics.topic_id=topics.topic_id)')
    finally:
        connection.close()
    from app.rag_engine import clear_result_cache
    clear_result_cache()
    if not keep_snapshot:
        shutil.rmtree(path.parent)


def library_menu() -> None:
    """Human-operated source manager; imports require a reviewed preview."""
    while True:
        print('\nROMS knowledge library\n1. Add a file\n2. Add a local Git repository'
              '\n3. Add a folder\n4. List sources\n5. Refresh a source\n6. Remove a source\n0. Exit')
        try:
            choice = input('Choose: ').strip()
            if choice == '0':
                return
            if choice in {'1', '2', '3'}:
                kind = {'1': 'file', '2': 'repo', '3': 'folder'}[choice]
                value = input('Paste the Windows or Linux path: ').strip().strip('"')
                _, files, skipped = plan_source(value, kind)
                print(f'{len(files)} files, {sum(len(data) for _, data in files):,} bytes; {len(skipped)} skipped.')
                for relative, _ in files[:30]:
                    print('  ' + relative.as_posix())
                if len(files) > 30:
                    print(f'  ... and {len(files) - 30} more')
                if input('Import this selection? Type yes: ').strip().lower() == 'yes':
                    result = add_source(value, kind)
                    print(f"Ready: {result['indexed_files']} files indexed. Source ID: {result['id']}")
            elif choice in {'4', '5', '6'}:
                sources = list_sources()
                for index, source in enumerate(sources, 1):
                    print(f"{index}. [{source['status']}] {source['origin']} ({source['id']})")
                if not sources:
                    print('No sources have been added.')
                elif choice != '4':
                    selected = int(input('Source number (0 to cancel): '))
                    if selected == 0:
                        continue
                    if not 1 <= selected <= len(sources):
                        raise ValueError('Choose one of the listed source numbers')
                    source = sources[selected - 1]
                    if choice == '5':
                        result = add_source(source['origin'], source['kind'])
                        remove_source(source['id'])
                        print(f"Refreshed: {result['indexed_files']} files indexed. Source ID: {result['id']}")
                    elif input('Remove the indexed copy? Original files stay intact. Type yes: ').strip().lower() == 'yes':
                        remove_source(source['id'])
                        print('Removed the indexed copy.')
            else:
                print('Choose a number from 0 to 6.')
        except (EOFError, KeyboardInterrupt):
            print('\nLibrary closed. Interrupted imports remain visible for removal or refresh.')
            return
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            print(f'Source operation failed: {error}')


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['file', 'repo', 'folder', 'list', 'remove', 'refresh', 'menu'])
    parser.add_argument('value', nargs='?')
    parser.add_argument('--preview', action='store_true')
    args = parser.parse_args()
    if args.preview and args.action in {'list', 'remove', 'menu'}:
        parser.error('--preview applies only to adding or refreshing sources')
    if args.action == 'menu':
        library_menu()
        return
    library = DATA_DIR / 'library'
    if args.action == 'list':
        print(json.dumps(list_sources(), indent=2))
        return
    if not args.value:
        parser.error('This action requires a path or source ID')
    if args.action == 'remove':
        remove_source(args.value)
        print('Removed source from the index; original files were preserved.')
        return
    previous = None
    if args.action == 'refresh':
        previous = args.value
        metadata = json.loads(_manifest_path(previous, library).read_text())
        args.action, args.value = metadata['kind'], metadata['origin']
    if args.preview:
        root, files, skipped = plan_source(args.value, args.action)
        print(json.dumps({'root': str(root), 'files': [str(path) for path, _ in files],
                          'bytes': sum(len(data) for _, data in files), 'skipped': skipped}, indent=2))
        return
    manifest = add_source(args.value, args.action)
    if previous:
        remove_source(previous)
    print(json.dumps({'id': manifest['id'], 'status': manifest['status'],
                      'files': len(manifest['files']), 'indexed_files': manifest['indexed_files'],
                      'skipped': manifest['skipped']}, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        raise SystemExit(f'Source operation failed: {error}') from error
