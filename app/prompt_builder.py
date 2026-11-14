"""Local LLM Context Engineering & Prompt Builder.

Optimized specifically for local open-weights LLMs (Llama 3, Qwen 2.5, Mistral, Gemma 2, Phi 3):
- Strict token budgeting to minimize TTFT (Time-To-First-Token) and memory footprint
- Exact text deduplication of retrieved RAG chunks
- Context grounding guardrails to prevent small model hallucinations
- Clean XML/Markdown structured context injection
"""

import re
from typing import Any, Dict, List, Optional
from app.config import MAX_RAG_CONTEXT_TOKENS, MIN_RELEVANCE_SCORE


def estimate_tokens(text: str) -> int:
    """Fast, lightweight token count estimation (approx 4 chars/token + word factor)."""
    if not text:
        return 0
    words = len(text.split())
    chars = len(text)
    return max(words, chars // 4)


def clean_chunk_text(text: str) -> str:
    """Strips excessive whitespace, repetitive header tags, and trailing artifacts."""
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    return text


def _candidates(chunks, min_score):
    """Keep ranked evidence and identity; a relevance score is not confidence."""
    seen = set()
    for item in chunks:
        if item.get("score", 0.0) < min_score:
            continue
        content = clean_chunk_text(item.get("content", ""))
        key = content
        if content and key not in seen:
            seen.add(key)
            yield {**item, "content": content}


def pack_evidence(chunks, budget, measure, min_score=0.0):
    """Pack whole passages first, counting their final representation.

    If no complete passage fits, retain a bounded prefix of the first one.
    The caller's measure is authoritative, including tokenizer/format overhead.
    """
    if type(budget) is not int or budget < 0:
        raise ValueError("Context budget must be a nonnegative integer")
    if budget == 0:
        return []
    candidates = list(_candidates(chunks, min_score))
    selected = []
    for item in candidates:
        if measure([*selected, item]) <= budget:
            selected.append(item)
    if selected or not candidates:
        return selected
    item = candidates[0]
    low, high, best = 1, len(item["content"]), []
    while low <= high:
        middle = (low + high) // 2
        prefix = {**item, "content": item["content"][:middle].rstrip() + "…", "truncated": True}
        if measure([prefix]) <= budget:
            best, low = [prefix], middle + 1
        else:
            high = middle - 1
    return best


def compress_chunks(
    chunks: List[Dict[str, Any]],
    max_tokens: int = MAX_RAG_CONTEXT_TOKENS,
    min_score: float = MIN_RELEVANCE_SCORE,
    *, token_counter=None,
) -> List[Dict[str, Any]]:
    """Budget passage text; supply the consuming tokenizer for exact counts."""
    count = token_counter or estimate_tokens
    return pack_evidence(chunks, max_tokens,
                         lambda items: sum(count(item["content"]) for item in items), min_score)


def source_label(item):
    """A compact citation, using only known source metadata."""
    fields = [str(item.get("doc_id", "doc"))]
    meta = item.get("source", {})
    if meta.get("page") is not None:
        fields.append(f"page {meta['page']}")
    if meta.get('slide') is not None:
        fields.append(f"slide {meta['slide']}")
    if meta.get('sheet'):
        fields.append(f"sheet {meta['sheet']}")
    if meta.get("section_path"):
        fields.append(" > ".join(meta["section_path"]))
    if meta.get("symbol"):
        fields.append(meta["symbol"])
    if item.get("chunk_id") is not None:
        fields.append(f"chunk {item['chunk_id']}")
    return " | ".join(fields)


def _render_context(items, style):
    from html import escape
    if not items:
        return ""
    if style == "xml":
        lines = ["<knowledge_context>"]
        for idx, item in enumerate(items, 1):
            doc = escape(str(item.get("doc_id", "doc")), quote=True)
            chunk = f' chunk="{escape(str(item["chunk_id"]), quote=True)}"' if item.get('chunk_id') is not None else ''
            location = f' citation="{escape(source_label(item), quote=True)}"' if item.get('source') else ''
            lines.append(f'  <source id="{idx}" doc="{doc}"{chunk}{location} relevance="{item.get("score", 0.0):.3f}">')
            lines.extend("    " + escape(line) for line in item["content"].split("\n"))
            lines.append("  </source>")
        return "\n".join([*lines, "</knowledge_context>"])
    lines = ["### Relevant Knowledge Context:"]
    for idx, item in enumerate(items, 1):
        lines.append(f"**[{idx}] Source: {source_label(item)}**\n{item['content']}\n")
    return "\n".join(lines)


def format_context_for_local_llm(
    chunks: List[Dict[str, Any]],
    format_style: str = "xml",
    max_tokens: int = MAX_RAG_CONTEXT_TOKENS,
    min_score: float = MIN_RELEVANCE_SCORE,
    *, token_counter=None,
) -> str:
    """Budget the complete rendered context, including escaped text and citations.

    Without a consumer tokenizer this enforces ROMS's estimate, not a claim
    about every language model's actual token count.
    """
    if format_style not in {"xml", "markdown"}:
        raise ValueError("Context format must be xml or markdown")
    count = token_counter or estimate_tokens
    selected = pack_evidence(chunks, max_tokens,
                             lambda items: count(_render_context(items, format_style)), min_score)
    return _render_context(selected, format_style)


def build_grounded_system_prompt(
    base_system_prompt: str = "",
    context_str: str = "",
) -> str:
    """Assembles a grounded system prompt that prevents small model hallucination."""
    grounding_rules = (
        "CRITICAL INSTRUCTIONS:\n"
        "1. Answer based STRICTLY on the facts provided in the knowledge context.\n"
        "2. If the context does not contain the answer, reply: "
        "'I do not have enough information to answer that based on the provided knowledge.'\n"
        "3. Do not invent, extrapolate, or assume facts outside the provided context.\n"
        "4. Be concise, direct, and actionable."
    )

    parts = []
    if base_system_prompt.strip():
        parts.append(base_system_prompt.strip())
    parts.append(grounding_rules)
    if context_str.strip():
        parts.append(context_str.strip())

    return "\n\n".join(parts)
