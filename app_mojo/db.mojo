"""Mojo SQLite and sqlite-vec + FTS5 Database Initialization and Management."""

from std.python import Python, PythonObject
from app_mojo.config import get_base_paths

def _get_pool() raises -> PythonObject:
    var builtins = Python.import_module("builtins")
    var has_pool = Python.evaluate("lambda b: hasattr(b, '_roms_pool')")(builtins)
    if not has_pool:
        var pool = Python.evaluate("{}")
        builtins._roms_pool = pool
        return pool
    return builtins._roms_pool

def get_connection(custom_db_path: PythonObject = Python.none()) raises -> PythonObject:
    """Creates or reuses a pooled SQLite connection with WAL mode enabled and sqlite-vec loaded."""
    var is_none = Python.evaluate("lambda x: x is None")(custom_db_path)
    var db_path_str: String
    if not is_none:
        db_path_str = String(custom_db_path)
    else:
        var paths = get_base_paths()
        var data_dir = paths[0]
        data_dir.mkdir(parents=True, exist_ok=True)
        db_path_str = String(paths[1])

    # Check pooled connection
    var pool = _get_pool()
    var has_key = Python.evaluate("lambda p, k: k in p")(pool, db_path_str)
    if has_key:
        var existing = pool[db_path_str]
        try:
            existing.execute("SELECT 1")
            return existing
        except:
            pass

    var sqlite3 = Python.import_module("sqlite3")
    var sqlite_vec = Python.import_module("sqlite_vec")
    var conn = sqlite3.connect(db_path_str, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA cache_size=-64000;")
    conn.execute("PRAGMA mmap_size=268435456;")
    conn.execute("PRAGMA temp_store=MEMORY;")
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    pool[db_path_str] = conn
    return conn

def init_database(custom_db_path: PythonObject = Python.none()) raises:
    """Initializes ROMS schema in SQLite: OKF registry, vec0 virtual table, FTS5 lexical table, and support tickets."""
    var db = Python.import_module("app.db")
    db.init_database(custom_db_path)
