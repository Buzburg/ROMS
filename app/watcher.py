"""ROMS Autonomous Background File Watcher.

Continuously monitors:
1. `knowledge/` -> Indexes supported text, documents and images into sqlite-vec + FTS5.
2. `skills/`     -> Detects new or edited SOP playbooks.
3. `custom_tools/` -> Hot-reloads and registers new Python MCP tools.

Runs on a daemon thread; extraction and OCR may take longer for large documents.
"""

import importlib.util
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from app.config import KNOWLEDGE_DIR, SKILLS_DIR, BASE_DIR
from app.mcp_annotations import plugin_allowed
from app.okf_loader import ingest_managed_file, scan_knowledge_files, prune_missing_knowledge

_WATCHER_THREAD: Optional[threading.Thread] = None
_STOP_EVENT = threading.Event()
_WATCHER_STATS: Dict[str, Any] = {
    "is_running": False,
    "last_event": "None",
    "reloads_count": 0,
    "monitored_paths": [],
}


def _reload_custom_tool(py_path: Path, mcp_instance: Any = None):
    """Dynamically reloads a single tool file from custom_tools/."""
    if py_path.name.startswith("__") or not plugin_allowed(py_path, BASE_DIR / "custom_tools", reload=True):
        return
    try:
        mod_name = f"custom_tools.{py_path.stem}"
        spec = importlib.util.spec_from_file_location(mod_name, py_path)
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = mod
            spec.loader.exec_module(mod)
            if mcp_instance and hasattr(mod, "register_tools"):
                mod.register_tools(mcp_instance)
                print(f"[ROMS Watcher] Hot-reloaded MCP tool: {py_path.name}", file=sys.stderr)
    except Exception as e:
        print(f"[ROMS Watcher Error] Failed reloading tool {py_path.name}: {e}", file=sys.stderr)


def _watcher_loop(mcp_instance: Any = None, poll_interval: float = 1.0):
    """Poll complete scans; retry failures with exponential backoff capped at 60s."""
    custom_dir = BASE_DIR / "custom_tools"
    dirs_to_watch = [KNOWLEDGE_DIR, SKILLS_DIR, custom_dir]
    for directory in (SKILLS_DIR, custom_dir):
        directory.mkdir(parents=True, exist_ok=True)

    _WATCHER_STATS["monitored_paths"] = [str(d) for d in dirs_to_watch]
    _WATCHER_STATS["is_running"] = True
    versions = {}
    retries = {}
    known_files = None
    # Knowledge is deliberately unacknowledged on startup: a prior startup scan
    # may have failed. Unchanged successful documents skip extraction by checksum.
    for directory in (SKILLS_DIR, custom_dir):
        for path in directory.glob("*"):
            try:
                if path.is_file():
                    stat = path.stat()
                    versions[str(path)] = (stat.st_mtime_ns, stat.st_size)
            except OSError:
                continue

    try:
        while not _STOP_EVENT.is_set():
            if _STOP_EVENT.wait(poll_interval):
                break
            for directory in dirs_to_watch:
                try:
                    if directory == KNOWLEDGE_DIR:
                        files, identity = scan_knowledge_files(directory)
                        current_files = {str(path) for path in files}
                        if known_files != current_files:
                            prune_missing_knowledge(directory, files, identity)
                            for missing in (known_files or set()) - current_files:
                                versions.pop(missing, None)
                                retries.pop(missing, None)
                            known_files = current_files
                    else:
                        files = list(directory.glob("*"))
                    for path in files:
                        if _STOP_EVENT.is_set():
                            break
                        if not path.is_file():
                            continue
                        key = str(path)
                        try:
                            stat = path.stat()
                        except OSError:
                            continue
                        version = (stat.st_mtime_ns, stat.st_size)
                        if versions.get(key) == version:
                            continue
                        failed_version, failures, due = retries.get(key, (None, 0, 0))
                        if failed_version == version and time.monotonic() < due:
                            continue
                        # Do not add a per-file sleep to the initial checksum scan.
                        # Changed files already observed by this watcher debounce.
                        if key in versions and _STOP_EVENT.wait(0.1):
                            break
                        _WATCHER_STATS["reloads_count"] += 1
                        if directory == KNOWLEDGE_DIR:
                            try:
                                changed = ingest_managed_file(path, KNOWLEDGE_DIR)
                            except Exception as error:
                                # Even writing the failure diagnostic can fail (e.g.
                                # a busy database). Keep that file eligible for retry.
                                print(f"[ROMS Watcher Error] {path.name}: {error}", file=sys.stderr)
                                changed = None
                            if changed is None:
                                failures = min(failures + 1, 7) if failed_version == version else 1
                                delay = min(2 ** (failures - 1), 60)
                                retries[key] = (version, failures, time.monotonic() + delay)
                                _WATCHER_STATS["last_event"] = f"Failed {path.name}; retry in {delay}s"
                                continue
                            _WATCHER_STATS["last_event"] = f"Processed {path.name}; indexed={changed}"
                        elif path.suffix.lower() == ".md" and directory == SKILLS_DIR:
                            _WATCHER_STATS["last_event"] = f"Updated skill {path.stem}"
                        elif path.suffix.lower() == ".py" and directory == custom_dir:
                            _reload_custom_tool(path, mcp_instance)
                            _WATCHER_STATS["last_event"] = f"Reloaded tool {path.name}"
                        versions[key] = version
                        retries.pop(key, None)
                except Exception as error:
                    print(f"[ROMS Watcher Exception] {error}", file=sys.stderr)
    finally:
        _WATCHER_STATS["is_running"] = False


def start_watcher(mcp_instance: Any = None) -> bool:
    """Spawns the background file watcher thread."""
    global _WATCHER_THREAD
    if _WATCHER_THREAD and _WATCHER_THREAD.is_alive():
        return True

    _STOP_EVENT.clear()
    _WATCHER_STATS["is_running"] = True
    _WATCHER_THREAD = threading.Thread(
        target=_watcher_loop,
        args=(mcp_instance,),
        daemon=True,
        name="ROMS-FileWatcher",
    )
    _WATCHER_THREAD.start()
    return True


def stop_watcher():
    """Stops the background file watcher."""
    _STOP_EVENT.set()
    _WATCHER_STATS["is_running"] = False
    global _WATCHER_THREAD
    if _WATCHER_THREAD and _WATCHER_THREAD.is_alive():
        _WATCHER_THREAD.join(timeout=2.0)


def get_watcher_status() -> Dict[str, Any]:
    """Returns telemetry of the watcher."""
    return dict(_WATCHER_STATS)
