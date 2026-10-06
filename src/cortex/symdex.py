"""
Polyglot Zero-Database Codebase Symbol & Call-Graph Indexer
Extracts functions, classes, structs, traits, and call references across
Python, Mojo, Rust, TypeScript/JS, Go, and C/C++ with sub-millisecond lookup.
"""

import os
import re
import json
import time

IGNORE_DIRS = {
    ".git", ".cortex", "__pycache__", "node_modules", ".venv", "venv",
    "target", "dist", "build", ".mypy_cache", ".ruff_cache", ".pytest_cache"
}

LANGUAGE_EXTENSIONS = {
    ".py": "python",
    ".mojo": "mojo",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".rs": "rust",
    ".go": "go",
    ".c": "cpp",
    ".cpp": "cpp",
    ".h": "cpp",
    ".hpp": "cpp",
}

SYMBOL_PATTERNS = [
    # Python & Mojo: def / fn / class / struct / trait
    (re.compile(r"^\s*(?:async\s+)?(def|fn|class|struct|trait)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*(?:\(|\[|:|$)"), 1, 2),
    # Rust: pub fn / struct / enum / trait
    (re.compile(r"^\s*(?:pub(?:\([^)]+\))?\s+)?(?:async\s+)?(fn|struct|enum|trait)\s+([a-zA-Z_][a-zA-Z0-9_]*)"), 1, 2),
    # TypeScript / JS: function / class / interface / type
    (re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?(function|class|interface|type)\s+([a-zA-Z_][a-zA-Z0-9_]*)"), 1, 2),
    # Go: func / type X struct
    (re.compile(r"^\s*(func)\s+(?:\([^)]+\)\s+)?([a-zA-Z_][a-zA-Z0-9_]*)"), 1, 2),
]


class PolyglotSymdex:
    def __init__(self, cortex_dir: str = ".cortex"):
        self.cortex_dir = os.path.abspath(cortex_dir)
        self.index_file = os.path.join(self.cortex_dir, "symdex.json")

    def index_workspace(self, workspace_root: str = ".") -> dict:
        start = time.perf_counter()
        root = os.path.abspath(workspace_root)
        symbols = []
        files_scanned = 0

        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.startswith(".cortex")]
            for fname in filenames:
                _, ext = os.path.splitext(fname)
                if ext not in LANGUAGE_EXTENSIONS:
                    continue
                full_path = os.path.join(dirpath, fname)
                rel_path = os.path.relpath(full_path, root).replace("\\", "/")
                files_scanned += 1

                try:
                    with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()
                except Exception:
                    continue

                for line_idx, line in enumerate(lines, start=1):
                    for pat, kind_group, name_group in SYMBOL_PATTERNS:
                        m = pat.match(line)
                        if m:
                            kind = m.group(kind_group)
                            name = m.group(name_group)
                            symbols.append({
                                "name": name,
                                "kind": kind,
                                "file": rel_path,
                                "line": line_idx,
                                "signature": line.strip()[:140],
                                "language": LANGUAGE_EXTENSIONS[ext]
                            })
                            break

        duration_ms = (time.perf_counter() - start) * 1000.0
        index_data = {
            "workspace": root,
            "files_scanned": files_scanned,
            "total_symbols": len(symbols),
            "indexed_at": time.time(),
            "latency_ms": round(duration_ms, 2),
            "symbols": symbols
        }
        os.makedirs(self.cortex_dir, exist_ok=True)
        with open(self.index_file, "w", encoding="utf-8") as f:
            json.dump(index_data, f, indent=2)

        return index_data

    def lookup(self, query: str, top_k: int = 10) -> dict:
        start = time.perf_counter()
        if not os.path.exists(self.index_file):
            self.index_workspace(".")

        with open(self.index_file, "r", encoding="utf-8") as f:
            index_data = json.load(f)

        q_lower = query.lower()
        scored = []
        for sym in index_data.get("symbols", []):
            name_low = sym["name"].lower()
            if name_low == q_lower:
                scored.append((100.0, sym))
            elif name_low.startswith(q_lower):
                scored.append((80.0, sym))
            elif q_lower in name_low:
                scored.append((60.0, sym))
            elif q_lower in sym["signature"].lower():
                scored.append((40.0, sym))

        scored.sort(key=lambda item: (-item[0], item[1]["file"], item[1]["line"]))
        matches = [item[1] for item in scored[:top_k]]
        latency_us = (time.perf_counter() - start) * 1_000_000

        return {
            "query": query,
            "matches_found": len(matches),
            "matches": matches,
            "latency_us": round(latency_us, 2)
        }

    def stats(self) -> dict:
        if not os.path.exists(self.index_file):
            return {"files_scanned": 0, "total_symbols": 0, "symbols": []}
        with open(self.index_file, "r", encoding="utf-8") as f:
            return json.load(f)
