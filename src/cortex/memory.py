"""
Hybrid Titans + Gated DeltaNet-2 Neural Associative Memory
Combines test-time surprise momentum (arXiv:2501.00663) with decoupled erase/write gates (arXiv:2605.22791).
"""

import os
import re
import json
import math
import time
import struct
import hashlib

HEAD_DIM = 64
MATRIX_SIZE = HEAD_DIM * HEAD_DIM


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

    for i, tok in enumerate(tokens):
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
    def __init__(self, cortex_dir: str = ".cortex"):
        self.cortex_dir = os.path.abspath(cortex_dir)
        self.mem_dir = os.path.join(self.cortex_dir, "memory")
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
        """
        Executes a fused Titans Surprise + Gated DeltaNet-2 Erase/Write step.
        Cleanly overwrites any existing value on `key` while tracking surprise magnitude.
        """
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
        """
        Surgically erases a key from the neural memory matrix using DeltaNet-2 pure erase gate
        (alpha_erase = 1.0, beta_write = 0.0) without disturbing orthogonal keys.
        """
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
        """
        Queries the neural memory matrix y = M_t * q and resolves the recalled vector
        against stored entries.
        """
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

        # Direct key hit or associative vector resolution
        best_entry = None
        best_sim = -1.0
        for k, entry in meta["entries"].items():
            val_vec = encode_unit_vector(entry["value"])
            sim = cosine_similarity(y_vec, val_vec)
            if k == query:
                sim += 0.25  # Exact key boost
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
