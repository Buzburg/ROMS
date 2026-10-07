"""ROMS Decision Maker: advisory lexical ranking with explicit abstention.

This Python implementation combines hashed word features, a deterministic
recurrent sketch, and hand-weighted lexical scores. Softmax values are normalized
heuristic scores, not calibrated probabilities of truth. No language model,
trained embedding model, or native kernel is loaded by this module.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import string
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


DEFAULT_STATE_DIR = os.environ.get(
    "ROMS_STATE_DIR",
    os.path.join(os.path.expanduser("~"), ".roms")
)

STOPWORDS = {
    "the", "and", "is", "in", "to", "of", "for", "with", "on", "as", "by",
    "an", "at", "it", "be", "are", "was", "were", "or", "that", "this", "from",
    "can", "will", "should", "would", "could", "has", "have", "had"
}

ADVISORY_METADATA = {
    "engine": "ROMS Decision Maker",
    "backend": "lexical_heuristic",
    "probabilities_calibrated": False,
    "advisory_only": True,
    "execution_allowed": False,
}


def _finite_number(value: Any) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _validate_settings(temperature: float, threshold: float, min_margin: float) -> None:
    if (not _finite_number(temperature) or temperature <= 0.0
            or not _finite_number(threshold) or not 0.0 <= threshold <= 1.0
            or not _finite_number(min_margin) or not 0.0 <= min_margin <= 1.0):
        raise ValueError("Invalid decision temperature or abstention settings")


# ============================================================================
# 1. SOFTMAX NORMALIZATION AND RANKING
# ============================================================================

@dataclass
class Decision:
    index: int
    probabilities: List[float]
    confidence: float
    margin: float
    concentration: float
    expected_score: float
    abstain: bool


def decide(
    logits: List[float],
    allowed: Optional[List[bool]] = None,
    temperature: float = 1.0,
    threshold: float = 0.55,
    min_margin: float = 0.08,
) -> Decision:
    """
    Normalized decision over option logits with probability margin,
    Shannon concentration, expected rubric score, and dual abstention gates.
    """
    if not isinstance(logits, list):
        raise ValueError("Decision logits must be a list")
    if allowed is None:
        allowed = [True] * len(logits)
    if not isinstance(allowed, list) or any(type(item) is not bool for item in allowed):
        raise ValueError("Decision mask must contain booleans")
    if len(logits) < 2 or len(logits) != len(allowed):
        raise ValueError("Decision needs matching logits and mask, at least two options")
    _validate_settings(temperature, threshold, min_margin)

    best = -1
    permitted_count = 0
    for i, val in enumerate(logits):
        if not _finite_number(val):
            raise ValueError("Non-finite decision logit")
        if allowed[i]:
            permitted_count += 1
            if best == -1 or val > logits[best]:
                best = i

    if best == -1 or permitted_count < 2:
        raise ValueError("At least two permitted decision options are required")

    probabilities: List[float] = []
    total = 0.0
    for i, val in enumerate(logits):
        p = math.exp((float(val) - float(logits[best])) / temperature) if allowed[i] else 0.0
        probabilities.append(p)
        total += p

    second = 0.0
    expected = 0.0
    entropy = 0.0
    for i in range(len(logits)):
        probabilities[i] /= total
        p_i = probabilities[i]
        expected += float(i) * p_i
        if p_i > 1e-15:
            entropy -= p_i * math.log(p_i)
        if i != best and p_i > second:
            second = p_i

    confidence = probabilities[best]
    margin = confidence - second
    max_entropy = math.log(permitted_count)
    concentration = 0.0
    if max_entropy > 1e-12:
        concentration = max(0.0, min(1.0, 1.0 - (entropy / max_entropy)))

    should_abstain = (confidence < threshold) or (margin < min_margin)
    return Decision(
        index=best,
        probabilities=[round(p, 6) for p in probabilities],
        confidence=round(confidence, 6),
        margin=round(margin, 6),
        concentration=round(concentration, 6),
        expected_score=round(expected, 6),
        abstain=should_abstain,
    )


def rank_options(context: List[float], options: List[List[float]]) -> List[float]:
    """Dot-product ranking for caller-supplied vectors."""
    if not isinstance(context, list) or not context or not isinstance(options, list) or len(options) < 2:
        raise ValueError("Empty embeddings or insufficient options")
    scores: List[float] = []
    for option in options:
        if not isinstance(option, list) or len(option) != len(context):
            raise ValueError("Embedding dimension mismatch")
        score = 0.0
        for c_val, o_val in zip(context, option):
            if not _finite_number(c_val) or not _finite_number(o_val):
                raise ValueError("Non-finite embedding value")
            score += float(c_val) * float(o_val)
        if not math.isfinite(score):
            raise ValueError("Embedding score overflow")
        scores.append(score)
    return scores


def distribution_from_logprobs(meta: Dict[str, Any], token_ids: List[int]) -> List[float]:
    """
    Extracts normalized option probabilities from single-token (`max_new_tokens=1`)
    SGLang `output_token_ids_logprobs` metadata. This is a parser, not a backend.
    """
    if (not isinstance(token_ids, list) or not 2 <= len(token_ids) <= 26
            or any(type(token) is not int or token < 0 for token in token_ids)
            or len(set(token_ids)) != len(token_ids)):
        raise ValueError("Supply 2..26 distinct nonnegative option token IDs")
    if (not isinstance(meta, dict) or type(meta.get("completion_tokens")) is not int
            or meta["completion_tokens"] != 1):
        raise ValueError("Decision scoring requires exactly one generated token")
    reason = meta.get("finish_reason") or {}
    if isinstance(reason, dict) and reason.get("type") == "abort":
        raise ValueError("Decision generation aborted")
    positions = meta.get("output_token_ids_logprobs")
    if (not isinstance(positions, list) or len(positions) != 1
            or not isinstance(positions[0], list) or not 2 <= len(positions[0]) <= 256):
        raise ValueError("Malformed output_token_ids_logprobs")
    values: Dict[int, float] = {}
    for entry in positions[0]:
        if not isinstance(entry, (list, tuple)) or len(entry) not in (2, 3):
            raise ValueError("Malformed token logprob entry")
        value, token = entry[:2]
        if (
            type(token) is not int
            or token < 0
            or token in values
            or type(value) not in (int, float)
            or (not _finite_number(value) and value != -math.inf)
            or value == math.inf
            or value > 0
        ):
            raise ValueError("Invalid token logprob entry")
        values[token] = float(value)
    if any(token not in values for token in token_ids):
        raise ValueError("Missing option token logprob")
    logits = [values[token] for token in token_ids]
    peak = max(logits)
    if not math.isfinite(peak):
        raise ValueError("Option token distribution has no finite probability mass")
    weights = [math.exp(x - peak) for x in logits]
    total = sum(weights)
    return [x / total for x in weights]


# ============================================================================
# 2. QUESTION VALIDATION: choice, noul, score
# ============================================================================

def validate_question(question: Dict[str, Any]) -> Dict[str, str]:
    """
    Validates a structured advisory decision question:
      - `choice`: 2..26 options (dict or list)
      - `noul`:   fixed yes/no binary verification
      - `score`:  2..10 ordered rubric descriptions mapped to '0'..'9'
    """
    if not isinstance(question, dict) or not set(question) <= {"id", "type", "question", "options"}:
        raise ValueError("Question requires id, type, question, and optional options")
    for key in ("id", "question"):
        if not isinstance(question.get(key), str) or not question[key].strip() or len(question[key]) > 4000:
            raise ValueError(f"Invalid question {key}")
    if len(question["id"]) > 64:
        raise ValueError("Question ID exceeds 64 characters")
    kind = question.get("type")
    if not isinstance(kind, str):
        raise ValueError("Question type must be choice, noul, or score")
    if kind == "noul":
        if "options" in question and question["options"] is not None:
            raise ValueError("Noul uses fixed yes/no labels")
        return {
            "yes": "Yes, true, affirmative, supported, allowed, or satisfied by the supplied evidence.",
            "no": "No, false, negative, contradicted, unsafe, or not established by the supplied evidence.",
        }
    options = question.get("options")
    if kind == "score":
        if not isinstance(options, list) or not (2 <= len(options) <= 10):
            raise ValueError("Score needs 2..10 ordered descriptions")
        options = {str(i): value for i, value in enumerate(options)}
    elif kind == "choice" and isinstance(options, list):
        if not (2 <= len(options) <= 26):
            raise ValueError("Choice needs 2..26 options")
        options = {string.ascii_uppercase[i]: value for i, value in enumerate(options)}

    if kind not in {"choice", "score"} or not isinstance(options, dict) or not (2 <= len(options) <= 26):
        raise ValueError("Choice needs 2..26 options")
    if any(
        not isinstance(k, str) or not k.strip() or len(k) > 64
        or not isinstance(v, str) or not v.strip() or len(v) > 2000
        for k, v in options.items()
    ):
        raise ValueError("Option IDs and descriptions must be nonempty bounded strings")
    return options


# ============================================================================
# 3. HASHED WORD FEATURES AND TOPIC WORD COUNTS
# ============================================================================

def tokenize_words(text: str) -> List[str]:
    """Alphanumeric word tokenizer, preserving negation terms."""
    words = re.findall(r"\b[a-zA-Z0-9_]{2,}\b", text.lower())
    return [w for w in words if w not in STOPWORDS]


def encode_hashed_vector(text: str, dim: int = 64) -> List[float]:
    """Normalize MD5 word/stem features; these are not semantic embeddings."""
    if not isinstance(text, str) or type(dim) is not int or not 1 <= dim <= 4096:
        raise ValueError("Hashed features require text and a dimension from 1..4096")
    vec = [0.0] * dim
    tokens = tokenize_words(text)
    for pos, tok in enumerate(tokens):
        stem = re.sub(r"(?:ing|ed|es|tion|ions|ly|s)$", "", tok)
        pos_weight = 1.0 + (0.15 / (1.0 + pos * 0.2))
        for item, mult in ((tok, 1.0), (stem, 0.85)):
            if not item:
                continue
            h = int(hashlib.md5(item.encode("utf-8")).hexdigest(), 16)
            for k in range(4):
                idx = (h + k * 31) % dim
                sign = 1.0 if ((h >> (k + 5)) & 1) == 0 else -1.0
                vec[idx] += sign * pos_weight * mult

    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 1e-12:
        vec = [x / norm for x in vec]
    return vec


@dataclass
class TopicRepresentation:
    topic_id: int
    name: str
    keywords: List[Tuple[str, float]]
    document_count: int
    centroid: List[float]
    sample_documents: List[str] = field(default_factory=list)


class ClassTFIDF:
    """Class-based word-frequency weights with an optional BM25-like formula."""

    def __init__(self, bm25_weighting: bool = True, top_n_words: int = 8):
        self.bm25_weighting = bm25_weighting
        self.top_n_words = top_n_words

    def fit_transform(
        self, cluster_documents: Dict[int, List[str]]
    ) -> Dict[int, List[Tuple[str, float]]]:
        num_classes = len(cluster_documents)
        if num_classes == 0:
            return {}

        class_tf: Dict[int, Dict[str, int]] = {}
        class_total_words: Dict[int, int] = {}
        global_tf: Dict[str, int] = {}

        for cid, docs in cluster_documents.items():
            class_tf[cid] = {}
            total_words = 0
            for doc in docs:
                tokens = tokenize_words(doc)
                total_words += len(tokens)
                for tok in tokens:
                    class_tf[cid][tok] = class_tf[cid].get(tok, 0) + 1
                    global_tf[tok] = global_tf.get(tok, 0) + 1
            class_total_words[cid] = max(1, total_words)

        total_global_words = sum(global_tf.values())
        avg_words_per_class = total_global_words / max(1, num_classes)

        topic_keywords: Dict[int, List[Tuple[str, float]]] = {}
        for cid, tf_dict in class_tf.items():
            word_scores: List[Tuple[str, float]] = []
            total_w = class_total_words[cid]
            for word, count in tf_dict.items():
                tf_norm = count / total_w
                f_t = global_tf.get(word, 1)
                if self.bm25_weighting:
                    idf = math.log(1.0 + max(0.0, (avg_words_per_class - f_t + 0.5) / (f_t + 0.5)))
                    if idf <= 0.0:
                        idf = math.log(1.0 + (avg_words_per_class / f_t))
                else:
                    idf = math.log(1.0 + (avg_words_per_class / f_t))
                score = tf_norm * max(0.01, idf)
                word_scores.append((word, round(score, 5)))

            word_scores.sort(key=lambda x: x[1], reverse=True)
            topic_keywords[cid] = word_scores[: self.top_n_words]

        return topic_keywords


class TopicDiscoveryEngine:
    """Greedy hashed-feature centroids with weighted words as candidate labels.

    This is a local heuristic, not the BERTopic package. Persistent mode retains
    the legacy state filename; in-memory mode never reads or writes that file.
    """

    def __init__(
        self,
        state_dir: Optional[str] = None,
        max_topics: int = 16,
        top_n_keywords: int = 6,
        distance_threshold: float = 0.55,
        persist: bool = True,
    ):
        if type(persist) is not bool:
            raise ValueError("persist must be a boolean")
        if (type(max_topics) is not int or not 1 <= max_topics <= 128
                or type(top_n_keywords) is not int or not 1 <= top_n_keywords <= 32
                or not _finite_number(distance_threshold) or not 0 <= distance_threshold <= 2):
            raise ValueError("Invalid topic discovery bounds")
        self.persist = persist
        self.state_dir = state_dir or DEFAULT_STATE_DIR
        self.state_path = os.path.join(self.state_dir, "bertopic_decisions.json")
        self.max_topics = max_topics
        self.top_n_keywords = top_n_keywords
        self.distance_threshold = distance_threshold
        self.ctfidf = ClassTFIDF(bm25_weighting=True, top_n_words=top_n_keywords)
        self.topics: Dict[int, TopicRepresentation] = {}
        self.documents: List[Dict[str, Any]] = []
        if self.persist:
            os.makedirs(self.state_dir, exist_ok=True)
            self._load()

    def _load(self):
        if not self.persist:
            return
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.documents = data.get("documents", [])
                for tid_str, tdata in data.get("topics", {}).items():
                    tid = int(tid_str)
                    self.topics[tid] = TopicRepresentation(
                        topic_id=tid,
                        name=tdata["name"],
                        keywords=[tuple(x) for x in tdata.get("keywords", [])],
                        document_count=tdata.get("document_count", 1),
                        centroid=tdata.get("centroid", []),
                        sample_documents=tdata.get("sample_documents", []),
                    )
            except Exception:
                self.topics = {}
                self.documents = []

    def _save(self):
        if not self.persist:
            return
        payload = {
            "documents": self.documents[-500:],
            "topics": {
                str(tid): {
                    "topic_id": rep.topic_id,
                    "name": rep.name,
                    "keywords": rep.keywords,
                    "document_count": rep.document_count,
                    "centroid": [round(x, 6) for x in rep.centroid],
                    "sample_documents": rep.sample_documents[-5:],
                }
                for tid, rep in self.topics.items()
            },
        }
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    @staticmethod
    def _cosine_distance(v1: List[float], v2: List[float]) -> float:
        dot = sum(a * b for a, b in zip(v1, v2))
        return max(0.0, 1.0 - dot)

    def add_document(self, text: str, doc_id: Optional[str] = None) -> Dict[str, Any]:
        """Assign bounded text to a hashed-feature centroid or create a topic."""
        if not isinstance(text, str) or not text.strip() or len(text.encode("utf-8")) > 20_000:
            raise ValueError("Topic text must be nonempty and at most 20,000 UTF-8 bytes")
        if doc_id is not None and (not isinstance(doc_id, str) or not doc_id.strip() or len(doc_id) > 128):
            raise ValueError("Topic document ID must be a nonempty string of at most 128 characters")
        if not doc_id:
            doc_id = f"doc_{len(self.documents) + 1}"
        vec = encode_hashed_vector(text)

        if not self.topics:
            tid = 0
            self.topics[tid] = TopicRepresentation(
                topic_id=tid,
                name="Topic_0",
                keywords=[],
                document_count=1,
                centroid=vec,
                sample_documents=[text[:240]],
            )
        else:
            best_tid = 0
            min_dist = 1e9
            for tid, rep in self.topics.items():
                dist = self._cosine_distance(vec, rep.centroid)
                if dist < min_dist:
                    min_dist = dist
                    best_tid = tid

            if min_dist > self.distance_threshold and len(self.topics) < self.max_topics:
                tid = len(self.topics)
                self.topics[tid] = TopicRepresentation(
                    topic_id=tid,
                    name=f"Topic_{tid}",
                    keywords=[],
                    document_count=1,
                    centroid=vec,
                    sample_documents=[text[:240]],
                )
            else:
                tid = best_tid
                rep = self.topics[tid]
                n = rep.document_count
                new_c = [(c * n + v) / (n + 1) for c, v in zip(rep.centroid, vec)]
                norm = math.sqrt(sum(x * x for x in new_c)) or 1.0
                rep.centroid = [x / norm for x in new_c]
                rep.document_count += 1
                if len(rep.sample_documents) < 5:
                    rep.sample_documents.append(text[:240])

        self.documents.append({"doc_id": doc_id, "text": text, "topic_id": tid})
        self.update_topics()
        self._save()
        rep = self.topics[tid]
        return {
            "topic_id": tid,
            "topic_name": rep.name,
            "keywords": rep.keywords,
            "document_count": rep.document_count,
            "suggested_option_description": self._synthesize_option_label(rep),
        }

    def update_topics(self):
        cluster_docs: Dict[int, List[str]] = {tid: [] for tid in self.topics}
        for doc in self.documents:
            tid = doc.get("topic_id", 0)
            if tid in cluster_docs:
                cluster_docs[tid].append(doc["text"])

        keywords_map = self.ctfidf.fit_transform(cluster_docs)
        for tid, kws in keywords_map.items():
            if tid in self.topics:
                self.topics[tid].keywords = kws
                if kws:
                    top_words = "_".join(w for w, _ in kws[:3])
                    self.topics[tid].name = f"topic_{tid}_{top_words}"

    @staticmethod
    def _synthesize_option_label(rep: TopicRepresentation) -> str:
        if not rep.keywords:
            return f"Emerging category #{rep.topic_id}"
        top_terms = ", ".join(w for w, _ in rep.keywords[:4])
        return f"Queries focusing on: {top_terms} (n={rep.document_count})"

    def summary(self) -> Dict[str, Any]:
        total = max(1, len(self.documents))
        topics_out = []
        for tid, rep in sorted(self.topics.items()):
            topics_out.append({
                "topic_id": tid,
                "name": rep.name,
                "document_count": rep.document_count,
                "saturation": round(rep.document_count / total, 4),
                "keywords": [{"word": w, "c_tf_idf": s} for w, s in rep.keywords],
                "suggested_option": self._synthesize_option_label(rep),
            })
        return {
            "total_documents": len(self.documents),
            "num_topics": len(self.topics),
            "topics": topics_out,
        }


# ============================================================================
# 4. DETERMINISTIC RECURRENT FEATURE SKETCH
# ============================================================================

class HashedStateHead:
    """A fixed-size numerical sketch of hashed words, with no trained weights.

    It neither runs a language model nor retains its recurrent state. Payload
    size assumes packed float64 values and excludes Python object overhead.
    """

    def __init__(self, state_dim: int = 24):
        if type(state_dim) is not int or not 1 <= state_dim <= 128:
            raise ValueError("State dimension must be an integer from 1..128")
        self.state_dim = state_dim
        self.state: List[float] = [0.0] * (state_dim * state_dim)
        self.ingested_tokens: int = 0

    def reset(self):
        self.state = [0.0] * (self.state_dim * self.state_dim)
        self.ingested_tokens = 0

    def fork_state(self) -> List[float]:
        """Copy the state list; cost is proportional to the configured matrix size."""
        return list(self.state)

    def ingest_context(self, text: str) -> Dict[str, Any]:
        """Fold bounded word features into a fixed-size matrix."""
        if not isinstance(text, str) or len(text.encode("utf-8")) > 128_000:
            raise ValueError("State context must be text of at most 128,000 UTF-8 bytes")
        dim = self.state_dim
        tokens = tokenize_words(text)
        for tok in tokens:
            h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
            key = [0.0] * dim
            val = [0.0] * dim
            decay = [0.96] * dim
            iclr = [0.18] * dim
            for i in range(dim):
                k_bit = 1.0 if ((h >> (i % 32)) & 1) == 0 else -1.0
                v_bit = 1.0 if ((h >> ((i + 11) % 32)) & 1) == 0 else -1.0
                key[i] = k_bit / math.sqrt(dim)
                val[i] = v_bit / math.sqrt(dim)

            # Deterministic recurrent update using fixed decay and hash-derived vectors.
            for i in range(dim):
                row_off = i * dim
                s_dot_k = 0.0
                for j in range(dim):
                    s_dot_k += self.state[row_off + j] * key[j]
                v_i = val[i]
                for j in range(dim):
                    idx = row_off + j
                    self.state[idx] = (
                        self.state[idx] * decay[j]
                        - s_dot_k * iclr[j] * key[j]
                        + v_i * key[j]
                    )
            self.ingested_tokens += 1

        state_bytes = len(self.state) * 8
        return {
            "ingested_tokens": self.ingested_tokens,
            "ingested_words": self.ingested_tokens,
            "state_dim": f"{dim}x{dim}",
            "state_bytes": state_bytes,
            "state_payload_bytes": state_bytes,
            "payload_format": "float64_equivalent_excluding_python_overhead",
            "model_state": False,
        }

    def readout_vector(self, forked_state: List[float], query_text: str) -> List[float]:
        """Read the copied feature sketch using a hashed question vector."""
        dim = self.state_dim
        if (not isinstance(forked_state, list) or len(forked_state) != dim * dim
                or any(not _finite_number(value) for value in forked_state)):
            raise ValueError("Invalid feature state")
        q_vec = encode_hashed_vector(query_text, dim=dim)
        out = [0.0] * dim
        for i in range(dim):
            row_off = i * dim
            acc = 0.0
            for j in range(dim):
                acc += forked_state[row_off + j] * q_vec[j]
            out[i] = acc + q_vec[i]
        norm = math.sqrt(sum(x * x for x in out)) or 1.0
        return [x / norm for x in out]


# ============================================================================
# Compatibility names are retained for existing callers and saved integrations.
BERTopicDiscoveryEngine = TopicDiscoveryEngine
GooseStateDecisionHead = HashedStateHead
encode_semantic_vector = encode_hashed_vector


# 5. ADVISORY DECISION MAKER
# ============================================================================

NEGATION_WORDS = {"not", "never", "no", "false", "failed", "missing", "absent", "forbidden", "deny", "unsafe", "invalid"}
AFFIRM_WORDS = {"yes", "true", "verified", "passed", "confirmed", "valid", "safe", "allowed", "supported", "present"}


class ROMSDecisionEngine:
    """Evaluate bounded questions with lexical heuristics and abstention.

    Outputs are advisory. Normalized scores do not establish factual truth or
    authorize actions. Set persist_discovery=False for requests with no state I/O.
    """

    def __init__(
        self,
        state_dir: Optional[str] = None,
        temperature: float = 0.35,
        threshold: float = 0.45,
        min_margin: float = 0.08,
        persist_discovery: bool = True,
    ):
        _validate_settings(temperature, threshold, min_margin)
        if type(persist_discovery) is not bool:
            raise ValueError("persist_discovery must be a boolean")
        self.state_dir = state_dir or DEFAULT_STATE_DIR
        self.temperature = temperature
        self.threshold = threshold
        self.min_margin = min_margin
        self.state_head = HashedStateHead(state_dim=24)
        self.discovery = TopicDiscoveryEngine(state_dir=self.state_dir, persist=persist_discovery)
        self.goose = self.state_head
        self.bertopic = self.discovery

    @staticmethod
    def _pack_state(state: Any) -> str:
        if isinstance(state, str):
            return state
        try:
            return json.dumps(state, sort_keys=True, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError, RecursionError) as error:
            raise ValueError("Decision state must be text or JSON-compatible data") from error

    @staticmethod
    def _grounding_reasons(evidence: str, question: str, kind: str, offered: Dict[str, str]) -> List[str]:
        """Fail conservatively where word overlap cannot support a suggestion."""
        evidence_words = set(tokenize_words(evidence))
        if not evidence_words:
            return ["evidence_missing"]
        question_words = set(tokenize_words(question)) - {
            "does", "did", "do", "verify", "check", "whether", "which", "what",
        }
        explicit_negation = {"not", "never", "no", "cannot", "without", "neither", "nor"}
        if (explicit_negation & (evidence_words | question_words)
                or re.search(r"\b\w+n['\u2019]t\b", f"{evidence} {question}", re.I)
                or (kind == "noul" and NEGATION_WORDS & evidence_words)):
            return ["ambiguous_negation"]
        if kind == "noul":
            uncertainty = {
                "may", "might", "can", "could", "would", "should", "will", "if",
                "pending", "planned", "scheduled", "expected", "unknown", "uncertain",
                "unconfirmed", "unverified", "hypothetical", "possible", "possibly",
                "probably", "perhaps", "assuming", "awaiting",
            }
            raw_words = set(re.findall(r"\b[a-z]+\b", f"{evidence} {question}".lower()))
            if uncertainty & raw_words:
                # A conservative vocabulary check, not temporal or semantic entailment.
                return ["uncertain_or_pending"]
        stem = lambda word: re.sub(r"(?:ing|ed|es|tion|ly|s)$", "", word)
        evidence_stems = {stem(word) for word in evidence_words}
        if kind == "noul":
            covered = sum(word in evidence_words or stem(word) in evidence_stems for word in question_words)
            if not question_words or covered / len(question_words) < 0.75:
                return ["evidence_not_relevant"]
        else:
            option_words = set(tokenize_words(" ".join(offered.values())))
            if not any(word in evidence_words or stem(word) in evidence_stems for word in option_words):
                return ["evidence_not_relevant"]
        return []

    def _score_option_pair(
        self,
        evidence_text: str,
        question_text: str,
        option_key: str,
        option_desc: str,
        state_readout: List[float],
        kind: str,
        option_index: int,
        total_options: int,
        position_index: int,
    ) -> float:
        """
        Computes the raw uncalibrated logit for a single option by fusing:
          1. Hashed feature similarity (Context+Question vs Option)
          2. Lexical & stem overlap between Evidence and Option
          3. Recurrent sketch readout dot-product
          4. Polarity / numeric rubric alignment for `noul` and `score` questions
        """
        combined_context = f"{evidence_text}\n{question_text}"
        ctx_vec64 = encode_hashed_vector(combined_context, dim=64)
        ev_vec64 = encode_hashed_vector(evidence_text, dim=64)
        opt_vec64 = encode_hashed_vector(f"{option_key} {option_desc}", dim=64)
        opt_vec24 = encode_hashed_vector(f"{option_key} {option_desc}", dim=24)

        # 1. Hashed feature dot-products.
        bi_sim = sum(a * b for a, b in zip(ctx_vec64, opt_vec64))
        ev_sim = sum(a * b for a, b in zip(ev_vec64, opt_vec64))

        # 2. Evidence-only overlap: the question cannot substantiate itself.
        ev_tokens = set(tokenize_words(evidence_text))
        ev_stems = {re.sub(r"(?:ing|ed|es|tion|ly|s)$", "", w) for w in ev_tokens}
        opt_tokens = tokenize_words(f"{option_key} {option_desc}")
        opt_stems = [re.sub(r"(?:ing|ed|es|tion|ly|s)$", "", w) for w in opt_tokens]

        overlap_hits = 0.0
        for tok, stem in zip(opt_tokens, opt_stems):
            if tok in ev_tokens:
                overlap_hits += 1.0
            elif stem and stem in ev_stems:
                overlap_hits += 0.75
        overlap_score = overlap_hits / max(1.0, math.sqrt(len(opt_tokens)))

        # 3. Recurrent feature sketch dot-product.
        state_sim = sum(a * b for a, b in zip(state_readout, opt_vec24))

        logit = (1.6 * bi_sim) + (1.4 * ev_sim) + (1.8 * overlap_score) + (0.9 * state_sim)

        # 4. Specialized alignment for `noul` (yes/no) and `score` (0..9 rubric)
        ev_lower = set(re.findall(r"\b[a-z0-9_]+\b", evidence_text.lower()))
        if kind == "noul":
            q_content_tokens = [
                w for w in tokenize_words(question_text)
                if w not in {"does", "did", "do", "is", "are", "was", "were", "should", "verify", "check", "whether"}
            ]
            q_stems = [re.sub(r"(?:ing|ed|es|tion|ly|s)$", "", w) for w in q_content_tokens]
            q_matches = sum(
                1.0 for w, s in zip(q_content_tokens, q_stems)
                if w in ev_tokens or (s and s in ev_stems)
            )
            q_coverage = q_matches / max(1.0, len(q_content_tokens))
            neg_count = len(ev_lower & NEGATION_WORDS)
            aff_count = len(ev_lower & AFFIRM_WORDS)

            if option_key == "yes":
                if q_coverage >= 0.45 and neg_count == 0:
                    logit += 1.35 * q_coverage + (0.35 * aff_count)
                elif neg_count > aff_count:
                    logit -= 1.25
            elif option_key == "no":
                if neg_count > aff_count or q_coverage < 0.25:
                    logit += 1.35 + (0.35 * neg_count)
                else:
                    logit -= 0.75

        elif kind == "score":
            # Detect explicit numeric ratings or sentiment cues in evidence
            norm_level = option_index / max(1, total_options - 1)
            pos_cues = len(ev_lower & {"excellent", "perfect", "complete", "passed", "optimal", "clean", "100", "high", "great", "verified"})
            neg_cues = len(ev_lower & {"broken", "failed", "error", "critical", "missing", "poor", "zero", "bad", "crash", "none"})
            mid_cues = len(ev_lower & {"partial", "moderate", "fair", "some", "minor", "average", "medium"})
            if pos_cues > neg_cues and pos_cues > mid_cues:
                target_norm = 0.90
            elif neg_cues > pos_cues and neg_cues > mid_cues:
                target_norm = 0.10
            elif mid_cues > 0:
                target_norm = 0.50
            else:
                target_norm = None

            if target_norm is not None:
                dist = abs(norm_level - target_norm)
                logit += 1.25 * (1.0 - 2.0 * dist)

        return logit

    def ask(
        self,
        state: Any,
        questions: List[Dict[str, Any]],
        reverse_debias: bool = True,
        temperature: Optional[float] = None,
        threshold: Optional[float] = None,
        min_margin: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Evaluate 1..12 structured questions against bounded state, sequentially.
        """
        start_time = time.perf_counter()
        if not isinstance(questions, list) or not (1 <= len(questions) <= 12):
            raise ValueError("Supply 1..12 independent questions")
        validated_options = [validate_question(q) for q in questions]
        if len({q["id"] for q in questions}) != len(questions):
            raise ValueError("Duplicate question ID")

        if type(reverse_debias) is not bool:
            raise ValueError("reverse_debias must be a boolean")
        temp = temperature if temperature is not None else self.temperature
        thresh = threshold if threshold is not None else self.threshold
        margin_gate = min_margin if min_margin is not None else self.min_margin
        _validate_settings(temp, thresh, margin_gate)

        evidence_text = self._pack_state(state)
        if len(evidence_text.encode("utf-8")) > 128_000:
            raise ValueError("Decision state exceeds 128 KB; compact with ContextSieve first")

        self.state_head.reset()
        state_meta = self.state_head.ingest_context(evidence_text)

        results: Dict[str, Any] = {}
        for question, offered in zip(questions, validated_options):
            q_start = time.perf_counter()
            qid = question["id"]
            kind = question["type"]
            q_text = question["question"]
            pairs = list(offered.items())
            n_opts = len(pairs)

            forked = self.state_head.fork_state()
            state_readout = self.state_head.readout_vector(forked, q_text)
            grounding_reasons = self._grounding_reasons(evidence_text, q_text, kind, offered)

            # Forward pass (A..Z)
            fwd_logits = [0.0] * n_opts if grounding_reasons else [
                self._score_option_pair(
                    evidence_text, q_text, k, desc, state_readout, kind, idx, n_opts, idx
                )
                for idx, (k, desc) in enumerate(pairs)
            ]
            fwd_dec = decide(fwd_logits, temperature=temp, threshold=thresh, min_margin=margin_gate)

            if reverse_debias:
                # Compatibility ordering check; this is not a language-model bias test.
                rev_pairs = list(reversed(pairs))
                rev_logits_raw = [0.0] * n_opts if grounding_reasons else [
                    self._score_option_pair(
                        evidence_text, q_text, k, desc, state_readout, kind, (n_opts - 1 - pos_i), n_opts, pos_i
                    )
                    for pos_i, (k, desc) in enumerate(rev_pairs)
                ]
                # Map reversed logits back to original option order and average
                rev_logits_aligned = list(reversed(rev_logits_raw))
                avg_logits = [(f + r) * 0.5 for f, r in zip(fwd_logits, rev_logits_aligned)]
                final_dec = decide(avg_logits, temperature=temp, threshold=thresh, min_margin=margin_gate)
                rev_dec = decide(rev_logits_aligned, temperature=temp, threshold=thresh, min_margin=margin_gate)
                permutation_agreed = (fwd_dec.index == rev_dec.index)
            else:
                final_dec = fwd_dec
                permutation_agreed = True

            mapped_probs = {
                pair[0]: round(prob, 6)
                for pair, prob in zip(pairs, final_dec.probabilities)
            }
            winning_key = pairs[final_dec.index][0]
            abstention_reasons = list(grounding_reasons)
            if final_dec.abstain:
                abstention_reasons.append("score_gate")
            if not permutation_agreed:
                abstention_reasons.append("permutation_disagreement")
            abstained = bool(abstention_reasons)

            topic_suggestion = None
            if abstained:
                topic_suggestion = self.discovery.add_document(
                    f"{q_text} | {evidence_text[:300]}", doc_id=f"abstain_{qid}_{int(time.time()*1000)}"
                )

            q_result: Dict[str, Any] = {
                **ADVISORY_METADATA,
                "id": qid,
                "type": kind,
                "choice": winning_key,
                "confidence": final_dec.confidence,
                "probabilities": mapped_probs,
                "margin": final_dec.margin,
                "concentration": final_dec.concentration,
                "abstained": abstained,
                "abstention_reasons": abstention_reasons,
                "permutation_agreed": permutation_agreed,
                "legend": dict(offered),
                "state_payload_bytes": state_meta["state_payload_bytes"],
                "goose_state_bytes": state_meta["state_bytes"],
                "elapsed_ms": round((time.perf_counter() - q_start) * 1000.0, 3),
            }
            if kind == "noul":
                q_result["noul"] = mapped_probs["yes"]
            elif kind == "score":
                expected_val = sum(int(k) * p for k, p in mapped_probs.items())
                q_result["score"] = round(expected_val, 4)
                q_result["score_normalized"] = round(expected_val / max(1, n_opts - 1), 4)
            if topic_suggestion is not None:
                q_result["topic_discovery"] = topic_suggestion
                q_result["bertopic_open_set_discovery"] = topic_suggestion

            results[qid] = q_result

        return {
            **ADVISORY_METADATA,
            "question_count": len(questions),
            "state": state_meta,
            "goose_state": state_meta,
            "total_elapsed_ms": round((time.perf_counter() - start_time) * 1000.0, 3),
            "results": results,
        }

    def decide_choice(
        self,
        state: Any,
        question: str,
        options: Dict[str, str] | List[str],
        threshold: Optional[float] = None,
        min_margin: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Advisory choice over 2..26 options."""
        q = {"id": "choice_q", "type": "choice", "question": question, "options": options}
        out = self.ask(state, [q], threshold=threshold, min_margin=min_margin)
        return out["results"]["choice_q"]

    def decide_noul(
        self,
        state: Any,
        question: str,
        threshold: Optional[float] = None,
        min_margin: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Advisory yes/no ranking; never use this heuristic as an authorization gate."""
        q = {"id": "noul_q", "type": "noul", "question": question}
        out = self.ask(state, [q], threshold=threshold, min_margin=min_margin)
        return out["results"]["noul_q"]

    def decide_score(
        self,
        state: Any,
        question: str,
        rubric: List[str],
        threshold: Optional[float] = None,
        min_margin: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Advisory ranking over 2..10 ordered rubric levels."""
        q = {"id": "score_q", "type": "score", "question": question, "options": rubric}
        out = self.ask(state, [q], threshold=threshold, min_margin=min_margin)
        return out["results"]["score_q"]

    def route(
        self,
        goal: str,
        routes: Dict[str, str],
        threshold: float = 0.45,
        margin: float = 0.08,
    ) -> Dict[str, Any]:
        """
        Suggest a route using the heuristic score gates; never authorize execution.
        """
        q = {
            "id": "route",
            "type": "choice",
            "question": "Which capability best fulfills the user request?",
            "options": routes,
        }
        res = self.ask({"goal": goal}, [q], reverse_debias=True, threshold=threshold, min_margin=margin)["results"]["route"]
        choice = res["choice"]
        accepted = (
            choice != "abstain"
            and not res["abstained"]
            and res["permutation_agreed"]
        )
        return {
            **ADVISORY_METADATA,
            "selected_route": choice if accepted else None,
            "accepted": accepted,
            "decision": res,
        }
