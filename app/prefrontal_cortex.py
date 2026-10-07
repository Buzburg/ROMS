"""
ROMS local context, memory and recovery tools.

Includes associative key memory, bounded diagnostic filtering, symbol lookup,
content-addressed file snapshots, heuristic action advice, text-based tool
ranking, context packing and a local telemetry report. These Python tools do
not load trained language-model weights or establish permission to execute.
Research influences and implementation boundaries are documented in docs/components.md.
"""

import os
import re
import sys
import html
import json
import math
import time
import struct
import hashlib
import argparse
from pathlib import Path

try:
    from app.config import DATA_DIR
    DEFAULT_STATE_DIR = str(Path(DATA_DIR) / "prefrontal")
except Exception:
    DEFAULT_STATE_DIR = ".roms_prefrontal"

HEAD_DIM = 64
MATRIX_SIZE = HEAD_DIM * HEAD_DIM
STATE_DIM = 128
ROUTER_DIM = 128

IGNORE_DIRS = {
    ".git", ".cortex", ".roms_prefrontal", "__pycache__", "node_modules", ".venv", "venv",
    "target", "dist", "build", ".mypy_cache", ".ruff_cache", ".pytest_cache", "data"
}


# ============================================================================
# 1. HYBRID TITANS + GATED DELTANET-2 NEURAL ASSOCIATIVE MEMORY
# ============================================================================

def l2_norm(vec: list) -> float:
    return math.sqrt(sum(x * x for x in vec))


def cosine_similarity(vec_a: list, vec_b: list) -> float:
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    na = l2_norm(vec_a)
    nb = l2_norm(vec_b)
    if na < 1e-8 or nb < 1e-8:
        return 0.0
    return dot / (na * nb)


def encode_unit_vector(text: str, dim: int = HEAD_DIM) -> list:
    """Projects a key or value string into an L2-normalized unit vector in R^dim."""
    vec = [0.0] * dim
    tokens = re.findall(r"[a-z0-9_]+", text.lower())
    if not tokens:
        tokens = [text.lower()]

    for tok in tokens:
        h = int(hashlib.sha256(tok.encode("utf-8")).hexdigest(), 16)
        for j in range(4):
            idx = (h + j * 19) % dim
            sign = 1.0 if ((h >> (j + 5)) & 1) == 0 else -1.0
            vec[idx] += sign

    norm = l2_norm(vec)
    if norm < 1e-8:
        vec[0] = 1.0
        return vec
    return [x / norm for x in vec]


def matvec(matrix: list, vec: list, dim: int = HEAD_DIM) -> list:
    out = [0.0] * dim
    for r in range(dim):
        offset = r * dim
        acc = 0.0
        for c in range(dim):
            acc += matrix[offset + c] * vec[c]
        out[r] = acc
    return out


class HybridNeuralMemory:
    def __init__(self, state_dir: str = None):
        self.state_dir = os.path.abspath(state_dir or DEFAULT_STATE_DIR)
        self.mem_dir = os.path.join(self.state_dir, "memory")
        self.w_path = os.path.join(self.mem_dir, "weights.bin")
        self.m_path = os.path.join(self.mem_dir, "momentum.bin")
        self.meta_path = os.path.join(self.mem_dir, "catalog.json")

    def _ensure_init(self):
        os.makedirs(self.mem_dir, exist_ok=True)
        if not os.path.exists(self.w_path):
            zeros = [0.0] * MATRIX_SIZE
            self._save_bin(self.w_path, zeros)
            self._save_bin(self.m_path, zeros)
        if not os.path.exists(self.meta_path):
            self._save_meta({
                "updates": 0,
                "erases": 0,
                "frobenius_norm": 0.0,
                "last_surprise": 0.0,
                "entries": {}
            })

    def _save_bin(self, path: str, vec: list):
        with open(path, "wb") as f:
            f.write(struct.pack(f"{len(vec)}f", *vec))

    def _load_bin(self, path: str) -> list:
        self._ensure_init()
        with open(path, "rb") as f:
            raw = f.read()
            return list(struct.unpack(f"{len(raw)//4}f", raw))

    def _load_meta(self) -> dict:
        self._ensure_init()
        with open(self.meta_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_meta(self, meta: dict):
        os.makedirs(self.mem_dir, exist_ok=True)
        with open(self.meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

    def remember(
        self,
        key: str,
        value: str,
        category: str = "architecture",
        alpha_erase: float = 1.0,
        beta_write: float = 1.0,
        eta_momentum: float = 0.25,
        gamma_decay: float = 1.0
    ) -> dict:
        """Executes a fused Titans Surprise + Gated DeltaNet-2 Erase/Write step."""
        start = time.perf_counter()
        weights = self._load_bin(self.w_path)
        momentum = self._load_bin(self.m_path)
        meta = self._load_meta()

        k_vec = encode_unit_vector(key)
        v_vec = encode_unit_vector(value)

        v_old = matvec(weights, k_vec)
        surprise = 0.5 * sum((o - t) ** 2 for o, t in zip(v_old, v_vec))

        norm_sq = 0.0
        mom_blend = 1.0 - alpha_erase

        for r in range(HEAD_DIM):
            offset = r * HEAD_DIM
            delta_r = (beta_write * v_vec[r]) - (gamma_decay * alpha_erase * v_old[r])
            for c in range(HEAD_DIM):
                idx = offset + c
                rank1 = delta_r * k_vec[c]
                s_new = (eta_momentum * momentum[idx]) + rank1
                w_new = (gamma_decay * weights[idx]) + rank1 + (mom_blend * s_new)
                momentum[idx] = s_new
                weights[idx] = w_new
                norm_sq += w_new * w_new

        v_post = matvec(weights, k_vec)
        post_cosine = cosine_similarity(v_post, v_vec) if beta_write > 0 else 0.0
        f_norm = math.sqrt(norm_sq)

        self._save_bin(self.w_path, weights)
        self._save_bin(self.m_path, momentum)

        meta["updates"] += 1
        meta["frobenius_norm"] = round(f_norm, 4)
        meta["last_surprise"] = round(surprise, 6)
        meta["entries"][key] = {
            "key": key,
            "value": value,
            "category": category,
            "surprise_at_write": round(surprise, 4),
            "timestamp": time.time()
        }
        self._save_meta(meta)

        latency_us = (time.perf_counter() - start) * 1_000_000
        return {
            "key": key,
            "value": value,
            "surprise": round(surprise, 6),
            "post_write_cosine": round(post_cosine, 6),
            "frobenius_norm": round(f_norm, 4),
            "latency_us": round(latency_us, 2)
        }

    def erase(self, key: str) -> dict:
        """Surgically erases a key using DeltaNet-2 pure erase gate (alpha_erase=1.0, beta_write=0.0)."""
        start = time.perf_counter()
        weights = self._load_bin(self.w_path)
        meta = self._load_meta()
        k_vec = encode_unit_vector(key)
        v_old = matvec(weights, k_vec)

        norm_sq = 0.0
        for r in range(HEAD_DIM):
            offset = r * HEAD_DIM
            delta_r = -v_old[r]
            for c in range(HEAD_DIM):
                idx = offset + c
                weights[idx] += delta_r * k_vec[c]
                norm_sq += weights[idx] * weights[idx]

        v_after = matvec(weights, k_vec)
        residual_mag = l2_norm(v_after)

        self._save_bin(self.w_path, weights)
        meta["erases"] = meta.get("erases", 0) + 1
        meta["frobenius_norm"] = round(math.sqrt(norm_sq), 4)
        if key in meta["entries"]:
            del meta["entries"][key]
        self._save_meta(meta)

        return {
            "key": key,
            "erased": True,
            "residual_magnitude": round(residual_mag, 6),
            "latency_us": round((time.perf_counter() - start) * 1_000_000, 2)
        }

    def recall(self, query: str) -> dict:
        """Queries the neural memory matrix y = M_t * q and resolves against stored entries."""
        start = time.perf_counter()
        weights = self._load_bin(self.w_path)
        meta = self._load_meta()
        q_vec = encode_unit_vector(query)
        y_vec = matvec(weights, q_vec)
        mag = l2_norm(y_vec)

        if mag < 1e-4 or not meta["entries"]:
            return {
                "query": query,
                "found": False,
                "value": None,
                "confidence": 0.0,
                "latency_us": round((time.perf_counter() - start) * 1_000_000, 2)
            }

        best_entry = None
        best_sim = -1.0
        for k, entry in meta["entries"].items():
            val_vec = encode_unit_vector(entry["value"])
            sim = cosine_similarity(y_vec, val_vec)
            if k == query:
                sim += 0.25
            if sim > best_sim:
                best_sim = sim
                best_entry = entry

        return {
            "query": query,
            "found": best_entry is not None,
            "key": best_entry["key"] if best_entry else None,
            "value": best_entry["value"] if best_entry else None,
            "category": best_entry["category"] if best_entry else None,
            "confidence": round(min(1.0, max(0.0, best_sim)), 4),
            "latency_us": round((time.perf_counter() - start) * 1_000_000, 2)
        }

    def stats(self) -> dict:
        return self._load_meta()


# ============================================================================
# 2. SNAPKV OBSERVATION-WINDOW & HIGH-ENTROPY DIAGNOSTIC CONTEXT SIEVE
# ============================================================================

CRITICAL_PATTERNS = [
    (re.compile(r"\b(?:error|exception|traceback|fatal|panic|failed|failure|assert|segfault)\b", re.I), 10.0),
    (re.compile(r"[a-zA-Z0-9_./\\-]+\.[a-zA-Z0-9]+:\d+(?::\d+)?"), 9.5),
    (re.compile(r'File\s+"[^"]+",\s+line\s+\d+'), 9.5),
    (re.compile(r"\b(?:warning|warn|deprecated|timeout|refused)\b", re.I), 5.0),
    (re.compile(r"^\s*(?:E\s+|\+\+\+|---|@@)\s*"), 8.0),
]

NOISE_PATTERNS = [
    re.compile(r"^\s*$"),
    re.compile(r"^[\s.=\-*#%]+$"),
    re.compile(r"\b(?:downloading|extracting|fetching|resolving|unpacking|compiling|building)\b.*\d+%", re.I),
    re.compile(r"^\s*(?:GET|POST|PUT|DELETE|HEAD|OPTIONS)\s+/.*\s+200\b"),
]


def shannon_entropy(line: str) -> float:
    if not line:
        return 0.0
    freq = {}
    n = len(line)
    for ch in line:
        freq[ch] = freq.get(ch, 0) + 1
    ent = 0.0
    for count in freq.values():
        p = count / n
        ent -= p * math.log2(p)
    return ent


class ContextSieve:
    def __init__(self, state_dir: str = None):
        self.state_dir = os.path.abspath(state_dir or DEFAULT_STATE_DIR)
        self.telemetry_file = os.path.join(self.state_dir, "sieve_telemetry.json")

    def _record_savings(self, raw_tokens: int, kept_tokens: int):
        os.makedirs(self.state_dir, exist_ok=True)
        data = {"compactions": 0, "raw_tokens": 0, "kept_tokens": 0, "saved_tokens": 0}
        if os.path.exists(self.telemetry_file):
            try:
                with open(self.telemetry_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                pass
        data["compactions"] += 1
        data["raw_tokens"] += raw_tokens
        data["kept_tokens"] += kept_tokens
        data["saved_tokens"] += max(0, raw_tokens - kept_tokens)
        with open(self.telemetry_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def compact(
        self,
        raw_text: str,
        max_lines: int = 35,
        pool_kernel: int = 3,
        obs_window: int = 5
    ) -> dict:
        start = time.perf_counter()
        lines = raw_text.splitlines()
        n = len(lines)
        raw_tokens = max(1, len(raw_text) // 4)

        if n <= max_lines:
            self._record_savings(raw_tokens, raw_tokens)
            return {
                "compacted_text": raw_text,
                "original_lines": n,
                "retained_lines": n,
                "raw_tokens": raw_tokens,
                "retained_tokens": raw_tokens,
                "tokens_saved": 0,
                "compression_pct": 0.0,
                "latency_ms": round((time.perf_counter() - start) * 1000.0, 3)
            }

        raw_scores = [0.0] * n
        seen_hashes = set()

        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                raw_scores[i] = -10.0
                continue

            norm_line = re.sub(r"\d+", "#", stripped)
            if norm_line in seen_hashes:
                raw_scores[i] = -5.0
                continue
            seen_hashes.add(norm_line)

            is_noise = False
            for np in NOISE_PATTERNS:
                if np.search(stripped):
                    is_noise = True
                    break
            if is_noise:
                raw_scores[i] = -8.0
                continue

            score = min(3.5, shannon_entropy(stripped) * 0.4)
            for pat, boost in CRITICAL_PATTERNS:
                if pat.search(stripped):
                    score += boost

            raw_scores[i] = score

        obs_start = max(0, n - obs_window)
        for i in range(obs_start, n):
            if lines[i].strip():
                raw_scores[i] = max(raw_scores[i], 7.5)

        pooled_scores = [0.0] * n
        half_k = pool_kernel // 2
        for i in range(n):
            if raw_scores[i] < -4.0:
                pooled_scores[i] = raw_scores[i]
                continue
            neighbor_boost = 0.0
            for offset in range(-half_k, half_k + 1):
                if offset == 0:
                    continue
                nb = i + offset
                if 0 <= nb < n and raw_scores[nb] >= 9.0:
                    neighbor_boost = max(neighbor_boost, raw_scores[nb] * 0.65)
            pooled_scores[i] = max(raw_scores[i], neighbor_boost)

        ranked_indices = sorted(range(n), key=lambda idx: pooled_scores[idx], reverse=True)
        selected_indices = sorted(ranked_indices[:max_lines])

        output_lines = []
        prev_idx = -1
        for idx in selected_indices:
            if prev_idx != -1 and idx > prev_idx + 1:
                omitted = idx - prev_idx - 1
                output_lines.append(f"  ... [{omitted} repetitive/low-entropy lines compacted by ROMS Sieve] ...")
            output_lines.append(lines[idx])
            prev_idx = idx

        compacted_text = "\n".join(output_lines)
        kept_tokens = max(1, len(compacted_text) // 4)
        saved_tokens = max(0, raw_tokens - kept_tokens)
        compression_pct = round((saved_tokens / raw_tokens) * 100.0, 2)

        self._record_savings(raw_tokens, kept_tokens)

        return {
            "compacted_text": compacted_text,
            "original_lines": n,
            "retained_lines": len(selected_indices),
            "raw_tokens": raw_tokens,
            "retained_tokens": kept_tokens,
            "tokens_saved": saved_tokens,
            "compression_pct": compression_pct,
            "latency_ms": round((time.perf_counter() - start) * 1000.0, 3)
        }

    def stats(self) -> dict:
        if not os.path.exists(self.telemetry_file):
            return {"compactions": 0, "raw_tokens": 0, "kept_tokens": 0, "saved_tokens": 0}
        with open(self.telemetry_file, "r", encoding="utf-8") as f:
            return json.load(f)


# ============================================================================
# 3. POLYGLOT ZERO-DATABASE CODEBASE SYMBOL & CALL-GRAPH INDEXER
# ============================================================================

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
    (re.compile(r"^\s*(?:async\s+)?(def|fn|class|struct|trait)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*(?:\(|\[|:|$)"), 1, 2),
    (re.compile(r"^\s*(?:pub(?:\([^)]+\))?\s+)?(?:async\s+)?(fn|struct|enum|trait)\s+([a-zA-Z_][a-zA-Z0-9_]*)"), 1, 2),
    (re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?(function|class|interface|type)\s+([a-zA-Z_][a-zA-Z0-9_]*)"), 1, 2),
    (re.compile(r"^\s*(func)\s+(?:\([^)]+\)\s+)?([a-zA-Z_][a-zA-Z0-9_]*)"), 1, 2),
]


class PolyglotSymdex:
    def __init__(self, state_dir: str = None):
        self.state_dir = os.path.abspath(state_dir or DEFAULT_STATE_DIR)
        self.index_file = os.path.join(self.state_dir, "symdex.json")

    def index_workspace(self, workspace_root: str = ".") -> dict:
        start = time.perf_counter()
        root = os.path.abspath(workspace_root)
        symbols = []
        files_scanned = 0

        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.startswith(".roms")]
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
                            symbols.append({
                                "name": m.group(name_group),
                                "kind": m.group(kind_group),
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
        os.makedirs(self.state_dir, exist_ok=True)
        with open(self.index_file, "w", encoding="utf-8") as f:
            json.dump(index_data, f, indent=2)

        return index_data

    def lookup(self, query: str, top_k: int = 10, workspace_root: str = ".") -> dict:
        start = time.perf_counter()
        if not os.path.exists(self.index_file):
            self.index_workspace(workspace_root)

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


# ============================================================================
# 4. COPY-ON-WRITE CONTENT-ADDRESSABLE WORKSPACE TIME MACHINE
# ============================================================================

class WorkspaceTimeMachine:
    def __init__(self, state_dir: str = None):
        self.state_dir = os.path.abspath(state_dir or DEFAULT_STATE_DIR)
        self.cas_dir = os.path.join(self.state_dir, "cas")
        self.manifest_file = os.path.join(self.state_dir, "snapshots.json")

    def _ensure_init(self):
        os.makedirs(self.cas_dir, exist_ok=True)
        if not os.path.exists(self.manifest_file):
            with open(self.manifest_file, "w", encoding="utf-8") as f:
                json.dump({"snapshots": []}, f, indent=2)

    def _load_manifest(self) -> dict:
        self._ensure_init()
        with open(self.manifest_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_manifest(self, data: dict):
        self._ensure_init()
        with open(self.manifest_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def snapshot(self, label: str = "Pre-tool checkpoint", workspace_root: str = ".") -> dict:
        start = time.perf_counter()
        self._ensure_init()
        root = os.path.abspath(workspace_root)
        manifest = self._load_manifest()

        files_map = {}
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                d for d in dirnames
                if d not in IGNORE_DIRS and os.path.abspath(os.path.join(dirpath, d)) != self.state_dir
            ]
            for fname in filenames:
                full_path = os.path.join(dirpath, fname)
                rel_path = os.path.relpath(full_path, root).replace("\\", "/")
                try:
                    with open(full_path, "rb") as f:
                        raw = f.read()
                except Exception:
                    continue

                sha = hashlib.sha256(raw).hexdigest()[:24]
                blob_path = os.path.join(self.cas_dir, sha)
                if not os.path.exists(blob_path):
                    with open(blob_path, "wb") as bf:
                        bf.write(raw)
                files_map[rel_path] = sha

        snap_id = f"snap_{len(manifest['snapshots']) + 1:03d}"
        snap_entry = {
            "id": snap_id,
            "label": label,
            "timestamp": time.time(),
            "files_tracked": len(files_map),
            "files": files_map
        }
        manifest["snapshots"].append(snap_entry)
        self._save_manifest(manifest)

        return {
            "id": snap_id,
            "label": label,
            "files_tracked": len(files_map),
            "latency_ms": round((time.perf_counter() - start) * 1000.0, 2)
        }

    def rewind(self, snapshot_id: str, workspace_root: str = ".") -> dict:
        start = time.perf_counter()
        root = os.path.abspath(workspace_root)
        manifest = self._load_manifest()

        target_snap = None
        for s in manifest["snapshots"]:
            if s["id"] == snapshot_id:
                target_snap = s
                break

        if target_snap is None:
            return {"success": False, "error": f"Snapshot '{snapshot_id}' not found"}

        restored_count = 0
        for rel_path, sha in target_snap["files"].items():
            blob_path = os.path.join(self.cas_dir, sha)
            if not os.path.exists(blob_path):
                continue
            dest_path = os.path.join(root, rel_path.replace("/", os.sep))
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            with open(blob_path, "rb") as bf:
                blob_bytes = bf.read()
            with open(dest_path, "wb") as df:
                df.write(blob_bytes)
            restored_count += 1

        return {
            "success": True,
            "snapshot_id": snapshot_id,
            "files_restored": restored_count,
            "latency_ms": round((time.perf_counter() - start) * 1000.0, 2)
        }

    def list_snapshots(self) -> list:
        return self._load_manifest().get("snapshots", [])


# ============================================================================
# 5. PRE-SIMULATION TRAJECTORY FORECASTER, LOOP BREAKER & JSON REPAIR SHIELD
# ============================================================================

HAZARD_RULES = [
    (re.compile(r"\brm\s+-(?:r|f|rf|fr)\b.*(?:/|\*)", re.I), 0.96, "Destructive recursive file deletion"),
    (re.compile(r"\bdrop\s+(?:table|database|schema)\b", re.I), 0.95, "Destructive SQL schema drop"),
    (re.compile(r"\btruncate\s+table\b", re.I), 0.88, "Destructive table truncation"),
    (re.compile(r"\bgit\s+push\s+.*--force\b", re.I), 0.85, "Force push overwriting remote history"),
    (re.compile(r"\bgit\s+reset\s+--hard\b", re.I), 0.82, "Hard git reset discarding uncommitted work"),
    (re.compile(r"\bmkfs\b|\bformat\s+[a-zA-Z]:", re.I), 0.98, "Filesystem format command"),
    (re.compile(r":\(\)\{\s*:\|:&\s*\};:", re.I), 0.99, "Fork bomb pattern"),
]


def encode_action_vector(text: str, dim: int = STATE_DIM) -> list:
    vec = [0.0] * dim
    tokens = re.findall(r"[a-z0-9_]+", text.lower())
    if not tokens:
        return [0.01] * dim
    for tok in tokens:
        h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
        for k in range(4):
            idx = (h + k * 31) % dim
            sign = 1.0 if ((h >> (k + 4)) & 1) == 0 else -1.0
            vec[idx] += sign
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 1e-8:
        vec = [x / norm for x in vec]
    return vec


class ExecutionShield:
    def __init__(self, state_dir: str = None):
        self.state_dir = os.path.abspath(state_dir or DEFAULT_STATE_DIR)
        self.history_file = os.path.join(self.state_dir, "shield_history.json")

    def _load_history(self) -> dict:
        os.makedirs(self.state_dir, exist_ok=True)
        if not os.path.exists(self.history_file):
            return {"goal": "General coding task", "recent_actions": [], "intercepts": 0, "repairs": 0}
        with open(self.history_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_history(self, data: dict):
        os.makedirs(self.state_dir, exist_ok=True)
        with open(self.history_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def forecast_action(self, action: str, goal: str = None) -> dict:
        start = time.perf_counter()
        hist = self._load_history()
        if goal:
            hist["goal"] = goal

        active_goal = hist.get("goal", "General coding task")
        cand_vec = encode_action_vector(action)
        goal_vec = encode_action_vector(active_goal)

        raw_align = cosine_similarity(cand_vec, goal_vec)
        goal_alignment = (raw_align + 1.0) * 0.5

        max_loop_sim = 0.0
        repeat_count = 0
        for prev_act in hist.get("recent_actions", [])[-3:]:
            sim = cosine_similarity(cand_vec, encode_action_vector(prev_act))
            if sim > max_loop_sim:
                max_loop_sim = sim
            if sim > 0.94:
                repeat_count += 1

        hazard_score = 0.0
        hazard_reason = None
        for pat, score, reason in HAZARD_RULES:
            if pat.search(action):
                if score > hazard_score:
                    hazard_score = score
                    hazard_reason = reason

        loop_penalty = max_loop_sim if repeat_count >= 2 else (max_loop_sim * 0.3)
        p_success = (
            0.55 * goal_alignment
            + 0.25 * (1.0 - loop_penalty)
            + 0.20 * (1.0 - hazard_score)
        )

        is_loop = repeat_count >= 2
        blocked = (hazard_score > 0.70) or is_loop or (p_success < 0.35)

        if blocked:
            hist["intercepts"] = hist.get("intercepts", 0) + 1
        else:
            hist.setdefault("recent_actions", []).append(action)
            hist["recent_actions"] = hist["recent_actions"][-10:]

        self._save_history(hist)

        verdict = "ALLOW"
        if hazard_score > 0.70:
            verdict = f"BLOCKED_HAZARD ({hazard_reason})"
        elif is_loop:
            verdict = "BLOCKED_LOOP (Agent stuck in repetitive action cycle)"
        elif blocked:
            verdict = "BLOCKED_LOW_FORECAST"

        return {
            "action": action,
            "verdict": verdict,
            "blocked": blocked,
            "p_success": round(p_success, 4),
            "goal_alignment": round(goal_alignment, 4),
            "loop_similarity": round(max_loop_sim, 4),
            "hazard_score": round(hazard_score, 4),
            "hazard_reason": hazard_reason,
            "latency_us": round((time.perf_counter() - start) * 1_000_000, 2)
        }

    def repair_tool_call(self, raw_llm_output: str, schema: dict = None) -> dict:
        start = time.perf_counter()
        text = raw_llm_output.strip()

        fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if fence_match:
            text = fence_match.group(1).strip()

        first_brace = text.find("{")
        if first_brace != -1:
            text = text[first_brace:]

        if "'" in text and '"' not in text:
            text = text.replace("'", '"')
        else:
            text = re.sub(r"(?<=[{,\s])'([^']+)'\s*:", r'"\1":', text)
            text = re.sub(r":\s*'([^']*)'(?=[,\s}])", r': "\1"', text)

        text = re.sub(r",\s*([}\]])", r"\1", text)

        open_braces = text.count("{") - text.count("}")
        open_brackets = text.count("[") - text.count("]")
        if open_brackets > 0:
            text += "]" * open_brackets
        if open_braces > 0:
            text += "}" * open_braces

        try:
            parsed = json.loads(text)
        except Exception as e:
            return {
                "valid": False,
                "error": str(e),
                "latency_us": round((time.perf_counter() - start) * 1_000_000, 2)
            }

        args_obj = parsed.get("arguments", parsed.get("parameters", {}))
        if schema and isinstance(args_obj, dict):
            props = schema.get("properties", {})
            for k, prop_spec in props.items():
                if k in args_obj:
                    val = args_obj[k]
                    target_type = prop_spec.get("type")
                    if target_type == "integer" and isinstance(val, str) and val.lstrip("-").isdigit():
                        args_obj[k] = int(val)
                    elif target_type == "number" and isinstance(val, str):
                        try:
                            args_obj[k] = float(val)
                        except ValueError:
                            pass
                    elif target_type == "boolean" and isinstance(val, str):
                        if val.lower() in ("true", "1", "yes"):
                            args_obj[k] = True
                        elif val.lower() in ("false", "0", "no"):
                            args_obj[k] = False
                elif "default" in prop_spec:
                    args_obj[k] = prop_spec["default"]

        hist = self._load_history()
        hist["repairs"] = hist.get("repairs", 0) + 1
        self._save_history(hist)

        return {
            "valid": True,
            "tool_call": parsed,
            "latency_us": round((time.perf_counter() - start) * 1_000_000, 2)
        }

    def stats(self) -> dict:
        return self._load_history()


# ============================================================================
# 6. BITNET B1.58 MULTIPLIER-FREE TERNARY MCP TOOL ROUTER
# ============================================================================

def encode_ternary_signature(text: str, dim: int = ROUTER_DIM) -> list:
    raw = [0.0] * dim
    tokens = re.findall(r"[a-z0-9_]+", text.lower())
    for tok in tokens:
        stem = re.sub(r"(?:ing|ed|es|s)$", "", tok)
        for item in (tok, stem):
            if not item:
                continue
            h = int(hashlib.md5(item.encode("utf-8")).hexdigest(), 16)
            for k in range(4):
                idx = (h + k * 29) % dim
                sign = 1.0 if ((h >> (k + 6)) & 1) == 0 else -1.0
                raw[idx] += sign

    gamma = sum(abs(x) for x in raw) / max(1, dim)
    if gamma < 1e-8:
        return [0] * dim

    inv_g = 1.0 / gamma
    ternary = []
    for x in raw:
        val = x * inv_g
        if val > 0.45:
            ternary.append(1)
        elif val < -0.45:
            ternary.append(-1)
        else:
            ternary.append(0)
    return ternary


def encode_int8_query(text: str, dim: int = ROUTER_DIM) -> list:
    raw = [0.0] * dim
    tokens = re.findall(r"[a-z0-9_]+", text.lower())
    for tok in tokens:
        stem = re.sub(r"(?:ing|ed|es|s)$", "", tok)
        for item in (tok, stem):
            if not item:
                continue
            h = int(hashlib.md5(item.encode("utf-8")).hexdigest(), 16)
            for k in range(4):
                idx = (h + k * 29) % dim
                sign = 1.0 if ((h >> (k + 6)) & 1) == 0 else -1.0
                raw[idx] += sign

    beta = max((abs(x) for x in raw), default=1.0)
    if beta < 1e-8:
        return [0] * dim
    scale = 127.0 / beta
    return [int(round(x * scale)) for x in raw]


class TernaryToolRouter:
    def route(self, query: str, tools: list, top_k: int = 3) -> dict:
        start = time.perf_counter()
        q_int8 = encode_int8_query(query)
        scored = []

        for tool in tools:
            desc = f"{tool.get('name', '')} {tool.get('description', '')}"
            t_sig = encode_ternary_signature(desc)

            int_acc = 0
            for w_ter, q_val in zip(t_sig, q_int8):
                if w_ter == 1:
                    int_acc += q_val
                elif w_ter == -1:
                    int_acc -= q_val

            scored.append((int_acc, tool))

        scored.sort(key=lambda item: item[0], reverse=True)
        selected = [item[1] for item in scored[:top_k]]
        pruned_count = max(0, len(tools) - len(selected))

        return {
            "query": query,
            "total_tools": len(tools),
            "selected_count": len(selected),
            "pruned_count": pruned_count,
            "token_reduction_pct": round((pruned_count / max(1, len(tools))) * 100.0, 1),
            "selected_tools": selected,
            "latency_us": round((time.perf_counter() - start) * 1_000_000, 2)
        }


# ============================================================================
# 7. RUNTIME PRIMITIVES (0/1 KNAPSACK, PROMPT LOOKUP, PREFIX TRIE, BINARYVEC)
# ============================================================================

def select_context(
    costs: list,
    utilities: list,
    budget: int,
    required: int = -1
) -> list:
    n = len(costs)
    if n != len(utilities) or n > 64 or budget < 0 or budget > 20000:
        raise ValueError("Invalid context selector dimensions or budget")
    if required < -1 or required >= n:
        raise ValueError("Invalid required record")
    total = 0
    for i in range(n):
        if costs[i] < 1 or costs[i] > 20000 or utilities[i] < 1 or utilities[i] > 1000000:
            raise ValueError("Invalid record cost or utility")
        total += costs[i]
    if required >= 0 and costs[required] > budget:
        raise ValueError("Required record cannot fit")
    if total <= budget:
        return list(range(n))

    remaining = budget - (costs[required] if required >= 0 else 0)
    width = remaining + 1
    scores = [0] * width
    decisions = [False] * (n * width)

    for i in range(n):
        if i == required:
            continue
        weight = costs[i]
        value = utilities[i]
        for capacity in range(remaining, weight - 1, -1):
            proposed = scores[capacity - weight] + value
            if proposed > scores[capacity]:
                scores[capacity] = proposed
                decisions[i * width + capacity] = True

    chosen = [i == required for i in range(n)]
    capacity = remaining
    for i in range(n - 1, -1, -1):
        if decisions[i * width + capacity]:
            chosen[i] = True
            capacity -= costs[i]

    return [i for i in range(n) if chosen[i]]


def prompt_lookup(history: list, window: int, limit: int) -> list:
    if window < 1 or limit < 1 or len(history) <= window:
        return []
    suffix = len(history) - window
    for offset in range(suffix):
        start = suffix - offset - 1
        matches = True
        for j in range(window):
            if history[start + j] != history[suffix + j]:
                matches = False
                break
        if matches:
            count = min(limit, len(history) - start - window)
            return [history[start + window + j] for j in range(count)]
    return []


def kv_bytes(
    layers: int,
    heads: int,
    head_dim: int,
    tokens: int,
    bytes_per_element: int
) -> int:
    if min(layers, heads, head_dim, tokens, bytes_per_element) < 1:
        raise ValueError("KV dimensions must be positive")
    size = 2
    for dimension in (layers, heads, head_dim, tokens, bytes_per_element):
        if size > 9_223_372_036_854_775_807 // dimension:
            raise OverflowError("KV size overflow")
        size *= dimension
    return size


class PrefixIndex:
    def __init__(self):
        self.nodes = [[-1, -1, -1, -1]]

    def insert(self, tokens: list, count: int, slot: int):
        parent = 0
        for i in range(count):
            node = self.nodes[parent][1]
            while node >= 0:
                if self.nodes[node][0] == tokens[i]:
                    break
                node = self.nodes[node][2]
            if node < 0:
                node = len(self.nodes)
                self.nodes.append([tokens[i], -1, self.nodes[parent][1], slot])
                self.nodes[parent][1] = node
            self.nodes[node][3] = slot
            parent = node

    def match(self, tokens: list) -> tuple:
        parent = 0
        slot = -1
        count = 0
        for i in range(max(0, len(tokens) - 1)):
            node = self.nodes[parent][1]
            while node >= 0:
                if self.nodes[node][0] == tokens[i]:
                    break
                node = self.nodes[node][2]
            if node < 0:
                break
            slot = self.nodes[node][3]
            count += 1
            parent = node
        return slot, count


class TokenBudget:
    def __init__(self, capacity: int):
        if capacity < 1:
            raise ValueError("token capacity must be positive")
        self.capacity = capacity
        self.reserved = 0

    def available(self, amount: int) -> bool:
        return 0 < amount <= (self.capacity - self.reserved)

    def acquire(self, amount: int):
        if not self.available(amount):
            raise RuntimeError("live token capacity exhausted")
        self.reserved += amount

    def release(self, amount: int):
        if amount < 1 or amount > self.reserved:
            raise ValueError("invalid token reservation release")
        self.reserved -= amount


class BinaryVector:
    def __init__(self, vec: list):
        self.dim = len(vec)
        num_words = (self.dim + 63) // 64
        self.words = [0] * num_words
        for i, val in enumerate(vec):
            if val >= 0.0:
                self.words[i // 64] |= (1 << (i % 64))

    def hamming_distance(self, other: "BinaryVector") -> int:
        return sum((w1 ^ w2).bit_count() for w1, w2 in zip(self.words, other.words))

    def similarity(self, other: "BinaryVector") -> float:
        return 1.0 - (self.hamming_distance(other) / max(1, self.dim))


# ============================================================================
# 8. INTERACTIVE DARK-MODE HTML TELEMETRY & NEURAL MEMORY EXPLORER
# ============================================================================

def generate_roms_dashboard(state_dir: str = None, output_path: str = "roms_dashboard.html") -> str:
    sdir = state_dir or DEFAULT_STATE_DIR
    mem_stats = HybridNeuralMemory(sdir).stats()
    sieve_stats = ContextSieve(sdir).stats()
    sym_stats = PolyglotSymdex(sdir).stats()
    snaps = WorkspaceTimeMachine(sdir).list_snapshots()
    shield_stats = ExecutionShield(sdir).stats()

    entries = list(mem_stats.get("entries", {}).values())
    symbols = sym_stats.get("symbols", [])[:25]

    mem_rows = ""
    for e in entries:
        mem_rows += f"""
        <tr>
          <td><code>{html.escape(str(e.get('key', '')))}</code></td>
          <td>{html.escape(str(e.get('value', '')))}</td>
          <td><span class="badge">{html.escape(str(e.get('category', '')))}</span></td>
          <td>{e.get('surprise_at_write', 0.0):.4f}</td>
        </tr>"""
    if not mem_rows:
        mem_rows = '<tr><td colspan="4" class="empty">No associative memories recorded yet.</td></tr>'

    sym_rows = ""
    for s in symbols:
        sym_rows += f"""
        <tr>
          <td><strong>{html.escape(s.get('name', ''))}</strong></td>
          <td><span class="badge">{html.escape(s.get('kind', ''))}</span></td>
          <td><code>{html.escape(s.get('file', ''))}:{s.get('line', 0)}</code></td>
          <td><span class="badge lang">{html.escape(s.get('language', ''))}</span></td>
        </tr>"""
    if not sym_rows:
        sym_rows = '<tr><td colspan="4" class="empty">Run <code>roms_symdex_lookup</code> to populate codebase graph.</td></tr>'

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>ROMS | Local harness telemetry</title>
  <style>
    :root {{
      --bg: #0b0f19;
      --card: #131b2e;
      --border: #23304d;
      --accent: #38bdf8;
      --emerald: #34d399;
      --amber: #fbbf24;
      --rose: #fb7185;
      --text: #f1f5f9;
      --muted: #94a3b8;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      padding: 2rem;
      line-height: 1.5;
    }}
    header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 2rem;
      padding-bottom: 1rem;
      border-bottom: 1px solid var(--border);
    }}
    h1 {{ font-size: 1.6rem; font-weight: 700; color: var(--accent); }}
    .subtitle {{ color: var(--muted); font-size: 0.9rem; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
      gap: 1.2rem;
      margin-bottom: 2rem;
    }}
    .card {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1.25rem;
    }}
    .kpi-label {{ color: var(--muted); font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.05em; }}
    .kpi-val {{ font-size: 1.9rem; font-weight: 700; margin-top: 0.4rem; color: var(--emerald); }}
    .kpi-val.accent {{ color: var(--accent); }}
    .kpi-val.amber {{ color: var(--amber); }}
    .kpi-val.rose {{ color: var(--rose); }}
    .section {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1.5rem;
      margin-bottom: 1.5rem;
    }}
    h2 {{ font-size: 1.15rem; margin-bottom: 1rem; color: var(--text); }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
    th, td {{ text-align: left; padding: 0.75rem; border-bottom: 1px solid var(--border); }}
    th {{ color: var(--muted); font-weight: 600; }}
    code {{ background: #090d16; padding: 0.2rem 0.4rem; border-radius: 4px; color: var(--accent); }}
    .badge {{
      background: rgba(56, 189, 248, 0.15);
      color: var(--accent);
      padding: 0.2rem 0.55rem;
      border-radius: 999px;
      font-size: 0.75rem;
    }}
    .empty {{ color: var(--muted); text-align: center; padding: 1.5rem; }}
  </style>
</head>
<body>
  <header>
    <div>
      <h1>ROMS harness telemetry</h1>
      <p class="subtitle">Decision Maker • RAG • OKF • MCP • Skills</p>
    </div>
    <span class="subtitle">Local statistics, not a readiness certificate</span>
  </header>

  <div class="grid">
    <div class="card">
      <div class="kpi-label">Estimated Context Tokens Saved</div>
      <div class="kpi-val">{sieve_stats.get('saved_tokens', 0):,}</div>
    </div>
    <div class="card">
      <div class="kpi-label">Memory Entries</div>
      <div class="kpi-val accent">{len(entries)}</div>
    </div>
    <div class="card">
      <div class="kpi-label">Memory Norm ||M||_F</div>
      <div class="kpi-val amber">{mem_stats.get('frobenius_norm', 0.0):.3f}</div>
    </div>
    <div class="card">
      <div class="kpi-label">Indexed Code Symbols</div>
      <div class="kpi-val accent">{sym_stats.get('total_symbols', 0):,}</div>
    </div>
    <div class="card">
      <div class="kpi-label">File Snapshots</div>
      <div class="kpi-val">{len(snaps)}</div>
    </div>
    <div class="card">
      <div class="kpi-label">Heuristic Hazard Flags</div>
      <div class="kpi-val rose">{shield_stats.get('intercepts', 0)}</div>
    </div>
  </div>

  <div class="section">
    <h2>Associative Memory Catalog</h2>
    <table>
      <thead>
        <tr><th>Key</th><th>Value</th><th>Category</th><th>Surprise Residual</th></tr>
      </thead>
      <tbody>{mem_rows}</tbody>
    </table>
  </div>

  <div class="section">
    <h2>Codebase Symbols (Top 25)</h2>
    <table>
      <thead>
        <tr><th>Symbol</th><th>Kind</th><th>Location</th><th>Language</th></tr>
      </thead>
      <tbody>{sym_rows}</tbody>
    </table>
  </div>
</body>
</html>"""

    out_abs = os.path.abspath(output_path)
    with open(out_abs, "w", encoding="utf-8") as f:
        f.write(html_doc)
    return out_abs


# ============================================================================
# 9. CLI ENTRYPOINT (`python -m app.prefrontal_cortex ...`)
# ============================================================================

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="ROMS local tools. Use 'python roms.py harness --help' for the preparation harness.")
    sub = parser.add_subparsers(dest="cmd")

    p_rem = sub.add_parser("remember")
    p_rem.add_argument("--key", required=True)
    p_rem.add_argument("--value", required=True)
    p_rem.add_argument("--category", default="architecture")

    p_rec = sub.add_parser("recall")
    p_rec.add_argument("--query", required=True)

    p_era = sub.add_parser("erase")
    p_era.add_argument("--key", required=True)

    p_sieve = sub.add_parser("sieve")
    p_sieve.add_argument("--max-lines", type=int, default=35)

    p_idx = sub.add_parser("index")
    p_idx.add_argument("--path", default=".")

    p_look = sub.add_parser("lookup")
    p_look.add_argument("--query", required=True)
    p_look.add_argument("--top-k", type=int, default=10)

    p_snap = sub.add_parser("snapshot")
    p_snap.add_argument("--label", default="Pre-tool checkpoint")
    p_snap.add_argument("--path", default=".")

    p_rew = sub.add_parser("rewind")
    p_rew.add_argument("--id", required=True)
    p_rew.add_argument("--path", default=".")

    p_fc = sub.add_parser("forecast")
    p_fc.add_argument("--action", required=True)
    p_fc.add_argument("--goal", default="General coding task")

    p_rep = sub.add_parser("repair")
    p_rep.add_argument("--raw", required=True)

    p_pack = sub.add_parser("pack")
    p_pack.add_argument("--costs", required=True)
    p_pack.add_argument("--values", required=True)
    p_pack.add_argument("--budget", type=int, required=True)
    p_pack.add_argument("--required", type=int, default=-1)

    p_draft = sub.add_parser("draft")
    p_draft.add_argument("--tokens", required=True)
    p_draft.add_argument("--ngram", type=int, default=2)
    p_draft.add_argument("--budget", type=int, default=4)

    p_dash = sub.add_parser("dashboard")
    p_dash.add_argument("--out", default="roms_dashboard.html")

    p_dec = sub.add_parser("decide")
    p_dec.add_argument("--state", required=True)
    p_dec.add_argument("--question", required=True)
    p_dec.add_argument("--options", required=True, help="JSON dict or comma-separated options")
    p_dec.add_argument("--threshold", type=float, default=0.45)
    p_dec.add_argument("--margin", type=float, default=0.08)

    p_noul = sub.add_parser("noul")
    p_noul.add_argument("--state", required=True)
    p_noul.add_argument("--question", required=True)
    p_noul.add_argument("--threshold", type=float, default=0.45)
    p_noul.add_argument("--margin", type=float, default=0.08)

    p_score = sub.add_parser("score")
    p_score.add_argument("--state", required=True)
    p_score.add_argument("--question", required=True)
    p_score.add_argument("--rubric", default="Poor,Fair,Good,Excellent")
    p_score.add_argument("--threshold", type=float, default=0.35)
    p_score.add_argument("--margin", type=float, default=0.05)

    p_top = sub.add_parser("topics")
    p_top.add_argument("--add", default="", help="Optional document for local topic suggestions")

    args = parser.parse_args(argv)
    if args.cmd == "remember":
        print(json.dumps(HybridNeuralMemory().remember(args.key, args.value, args.category), indent=2))
    elif args.cmd == "recall":
        print(json.dumps(HybridNeuralMemory().recall(args.query), indent=2))
    elif args.cmd == "erase":
        print(json.dumps(HybridNeuralMemory().erase(args.key), indent=2))
    elif args.cmd == "sieve":
        raw = sys.stdin.read()
        print(json.dumps(ContextSieve().compact(raw, max_lines=args.max_lines), indent=2))
    elif args.cmd == "index":
        print(json.dumps(PolyglotSymdex().index_workspace(args.path), indent=2))
    elif args.cmd == "lookup":
        print(json.dumps(PolyglotSymdex().lookup(args.query, top_k=args.top_k), indent=2))
    elif args.cmd == "snapshot":
        print(json.dumps(WorkspaceTimeMachine().snapshot(args.label, args.path), indent=2))
    elif args.cmd == "rewind":
        print(json.dumps(WorkspaceTimeMachine().rewind(args.id, args.path), indent=2))
    elif args.cmd == "forecast":
        print(json.dumps(ExecutionShield().forecast_action(args.action, args.goal), indent=2))
    elif args.cmd == "repair":
        print(json.dumps(ExecutionShield().repair_tool_call(args.raw), indent=2))
    elif args.cmd == "pack":
        costs = [int(x) for x in args.costs.split(",") if x.strip()]
        vals = [int(x) for x in args.values.split(",") if x.strip()]
        picked = select_context(costs, vals, args.budget, args.required)
        print(json.dumps({"selected_indices": picked}, indent=2))
    elif args.cmd == "draft":
        toks = [int(x) for x in args.tokens.split(",") if x.strip()]
        print(json.dumps({"drafted_tokens": prompt_lookup(toks, args.ngram, args.budget)}, indent=2))
    elif args.cmd == "dashboard":
        out = generate_roms_dashboard(output_path=args.out)
        print(json.dumps({"dashboard_path": out}, indent=2))
    elif args.cmd == "decide":
        from app.decisions import ROMSDecisionEngine
        try:
            opts = json.loads(args.options)
        except Exception:
            opts = [x.strip() for x in args.options.split(",") if x.strip()]
        res = ROMSDecisionEngine(threshold=args.threshold, min_margin=args.margin).decide_choice(
            state=args.state, question=args.question, options=opts
        )
        print(json.dumps(res, indent=2))
    elif args.cmd == "noul":
        from app.decisions import ROMSDecisionEngine
        res = ROMSDecisionEngine(threshold=args.threshold, min_margin=args.margin).decide_noul(
            state=args.state, question=args.question
        )
        print(json.dumps(res, indent=2))
    elif args.cmd == "score":
        from app.decisions import ROMSDecisionEngine
        rubric = [x.strip() for x in args.rubric.split(",") if x.strip()]
        res = ROMSDecisionEngine(threshold=args.threshold, min_margin=args.margin).decide_score(
            state=args.state, question=args.question, rubric=rubric
        )
        print(json.dumps(res, indent=2))
    elif args.cmd == "topics":
        from app.decisions import ROMSDecisionEngine
        eng = ROMSDecisionEngine()
        if args.add.strip():
            added = eng.bertopic.add_document(args.add.strip())
            print(json.dumps({"assigned_topic": added, "catalog": eng.bertopic.summary()}, indent=2))
        else:
            print(json.dumps(eng.bertopic.summary(), indent=2))
    else:
        parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
