"""ROMS Autonomous Background File Watcher.

Continuously monitors:
1. `knowledge/` -> Indexes supported text, documents and images into sqlite-vec + FTS5.
2. `skills/`     -> Detects new or edited SOP playbooks.
3. `custom_tools/` -> Hot-reloads and registers new Python MCP tools.

Runs on a daemon thread; extraction and OCR may take longer for large documents.
"""

import importlib.util
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Set

from app.config import KNOWLEDGE_DIR, SKILLS_DIR, BASE_DIR
from app.okf_loader import ingest_managed_file, knowledge_files

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
    if py_path.name.startswith("__"):
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
    """Polling loop with mtime tracking and debouncing."""
    custom_dir = BASE_DIR / "custom_tools"
    dirs_to_watch = [KNOWLEDGE_DIR, SKILLS_DIR, custom_dir]
    for d in dirs_to_watch:
        d.mkdir(parents=True, exist_ok=True)

    _WATCHER_STATS["monitored_paths"] = [str(d) for d in dirs_to_watch]
    _WATCHER_STATS["is_running"] = True

    mtimes: Dict[str, float] = {}

    # Initialize existing file mtimes
    for d in dirs_to_watch:
        for f in (knowledge_files(d) if d == KNOWLEDGE_DIR else d.glob("*")):
            if f.is_file():
                try:
                    mtimes[str(f)] = f.stat().st_mtime
                except Exception:
                    pass

    while not _STOP_EVENT.is_set():
        time.sleep(poll_interval)
        try:
            for d in dirs_to_watch:
                for f in (knowledge_files(d) if d == KNOWLEDGE_DIR else d.glob("*")):
                    if not f.is_file():
                        continue
                    f_str = str(f)
                    try:
                        current_mtime = f.stat().st_mtime
                    except Exception:
                        continue

                    last_mtime = mtimes.get(f_str, 0.0)
                    if current_mtime != last_mtime:
                        # Debounce wait for write completion
                        time.sleep(0.1)
                        mtimes[f_str] = current_mtime
                        _WATCHER_STATS["reloads_count"] += 1

                        if d == KNOWLEDGE_DIR:
                            _WATCHER_STATS["last_event"] = f"Ingested {f.name}"
                            print(f"[ROMS Watcher] Hot-indexing knowledge file: {f.name}", file=sys.stderr)
                            changed = ingest_managed_file(f, KNOWLEDGE_DIR)
                            _WATCHER_STATS["last_event"] = f"Processed {f.name}; indexed={changed}"

                        elif f.suffix.lower() == ".md" and d == SKILLS_DIR:
                            _WATCHER_STATS["last_event"] = f"Updated skill {f.stem}"
                            print(f"[ROMS Watcher] Detected skill update: {f.stem}", file=sys.stderr)

                        elif f.suffix.lower() == ".py" and d == custom_dir:
                            _WATCHER_STATS["last_event"] = f"Reloaded tool {f.name}"
                            _reload_custom_tool(f, mcp_instance)

        except Exception as e:
            print(f"[ROMS Watcher Exception] {e}", file=sys.stderr)

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
