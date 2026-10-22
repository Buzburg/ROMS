"""Durable local import queue. SQLite records progress; originals stay in managed storage."""
from contextlib import contextmanager
import os
from pathlib import Path
import threading
import uuid

from app.config import DATA_DIR, DB_PATH
from app.db import get_connection, init_database
from app.document_parse import MAX_FILE_BYTES
from app.okf_loader import SUPPORTED_EXTENSIONS, ingest_document_file


class Intake:
    def __init__(self, db_path=None, storage=None):
        self.db_path = Path(db_path or DB_PATH).resolve()
        self.storage = Path(storage or DATA_DIR / 'imports').resolve()
        self.storage.mkdir(parents=True, exist_ok=True, mode=0o700)
        init_database(self.db_path)
        with self.connection() as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS import_jobs (id TEXT PRIMARY KEY, name TEXT NOT NULL, path TEXT NOT NULL, state TEXT NOT NULL, error TEXT NOT NULL DEFAULT "", attempts INTEGER NOT NULL DEFAULT 0, created TEXT DEFAULT CURRENT_TIMESTAMP, updated TEXT DEFAULT CURRENT_TIMESTAMP)')
        self.stop = threading.Event()
        self.thread = None

    @contextmanager
    def connection(self):
        conn = get_connection(self.db_path, reuse=False)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def submit(self, name, content):
        from app.source_library import _admitted
        if not isinstance(name, str):
            raise ValueError("Filename must be text")
        relative = Path(name)
        if (not isinstance(name, str) or not name or len(name) > 500 or '\\' in name
                or '\x00' in name or relative.is_absolute() or '..' in relative.parts
                or any(part.startswith('.') for part in relative.parts) or not _admitted(relative)):
            raise ValueError('Use a supported document filename without hidden, secret or parent paths')
        if not content or len(content) > MAX_FILE_BYTES:
            raise ValueError('Each document must contain 1 byte to 32 MiB')
        job_id = uuid.uuid4().hex
        path = self.storage / (job_id + relative.suffix.lower())
        # A random exclusive filename makes the caller's name display-only.
        with path.open('xb') as output:
            os.chmod(path, 0o600)
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        try:
            with self.connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                if conn.execute("SELECT count(*) FROM import_jobs WHERE state IN ('queued','processing')").fetchone()[0] >= 1000:
                    raise ValueError('Queue is full (1,000 pending documents); wait for processing')
                conn.execute('INSERT INTO import_jobs(id,name,path,state) VALUES (?,?,?,?)',
                             (job_id, name, str(path), 'queued'))
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return job_id

    def status(self, offset=0, limit=50):
        with self.connection() as conn:
            counts = dict(conn.execute('SELECT state,count(*) FROM import_jobs GROUP BY state'))
            jobs = [dict(zip(('id', 'name', 'state', 'error', 'attempts', 'updated'), row)) for row in conn.execute(
                'SELECT id,name,state,error,attempts,updated FROM import_jobs ORDER BY created DESC,rowid DESC LIMIT ? OFFSET ?',
                (max(1, min(int(limit), 100)), max(0, int(offset))))]
        return {'counts': counts, 'jobs': jobs}

    def retry(self, job_id):
        with self.connection() as conn:
            return conn.execute("UPDATE import_jobs SET state='queued',error='',updated=CURRENT_TIMESTAMP WHERE id=? AND state='failed'", (job_id,)).rowcount == 1

    @contextmanager
    def worker_lock(self):
        # OS releases the lock even on a crash, unlike a timeout guessed from OCR duration.
        with self.db_path.with_suffix(self.db_path.suffix + '.intake.lock').open('a+b') as lock:
            if os.name == 'nt':
                import msvcrt
                lock.seek(0)
                lock.write(b'0')
                lock.flush()
                lock.seek(0)
                try:
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError:
                    yield False
                    return
            else:
                import fcntl
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    yield False
                    return
            try:
                yield True
            finally:
                if os.name == 'nt':
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock, fcntl.LOCK_UN)

    def recover(self):
        """Called only while holding the exclusive worker lock."""
        with self.connection() as conn:
            conn.execute("UPDATE import_jobs SET state='queued' WHERE state='processing'")

    def process_one(self):
        """Process one job while holding worker_lock; failed documents do not stop the queue."""
        with self.connection() as conn:
            row = conn.execute("SELECT id,path FROM import_jobs WHERE state='queued' ORDER BY rowid LIMIT 1").fetchone()
            if not row:
                return False
            job_id, path = row
            conn.execute("UPDATE import_jobs SET state='processing',attempts=attempts+1,updated=CURRENT_TIMESTAMP WHERE id=?", (job_id,))
        try:
            if not Path(path).is_file():
                raise ValueError('Original snapshot is missing')
            with self.connection() as conn:
                name = conn.execute('SELECT name FROM import_jobs WHERE id=?', (job_id,)).fetchone()[0]
            ingest_document_file(path, self.db_path, doc_id='import:' + job_id, display_name=name)
        except Exception as error:
            state, detail = 'failed', f'{type(error).__name__}: {error}'[:2000]
        else:
            state, detail = 'ready', ''
        with self.connection() as conn:
            conn.execute('UPDATE import_jobs SET state=?,error=?,updated=CURRENT_TIMESTAMP WHERE id=?', (state, detail, job_id))
        return True

    def run(self):
        from app.knowledge_skills import rebuild
        rebuild(self.db_path)
        while not self.stop.is_set():
            with self.worker_lock() as acquired:
                if acquired:
                    self.recover()
                    while not self.stop.is_set():
                        if not self.process_one():
                            self.stop.wait(0.5)
            self.stop.wait(0.5)

    def start(self):
        if not self.thread or not self.thread.is_alive():
            self.stop.clear()
            self.thread = threading.Thread(target=self.run, name='ROMS-Import', daemon=True)
            self.thread.start()
        return self
