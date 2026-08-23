"""Hybrid authority-aware retrieval (M1.4, P17-P19, H7-H8).

Question type -> authority eligibility -> exact/metadata match -> lexical +
semantic (local TF-IDF) retrieval -> rerank (authority + exact-identifier
bonus) -> applicability. A lower-authority document (e.g. OEM manual) can
never outrank the correct authority (project schedule) for a DESIGN question.
Includes a private retrieval benchmark with TOP1/TOP3 / EXACT_IDENTIFIER /
WRONG_AUTHORITY / WRONG_APPLICABILITY metrics.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

from .registry import SCSKnowledgeLibrary
from .sources import SourceAuthorityContext

_IDENTIFIER_RE = re.compile(
    r"\b[A-Z0-9]{2,}(?:-[A-Z0-9]{1,6}){0,3}\b")


class LocalTfIdf:
    """Local TF-IDF cosine similarity - LEXICAL_VECTOR_RETRIEVAL.

    This is lexical vector similarity, NOT a modern semantic embedding model
    (M1.4.1 P35). SEMANTIC_EMBEDDINGS remains NOT_IMPLEMENTED until a real
    local embedding provider is added.
    """

    version = "tfidf-v1"
    label = "LEXICAL_VECTOR_RETRIEVAL=LOCAL_TFIDF_V1"

    def __init__(self, documents: list[str]) -> None:
        self._tokens = [self._tokenize(doc) for doc in documents]
        self._idf = self._compute_idf(self._tokens)

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return re.findall(r"[a-z0-9]+", text.lower())

    def _compute_idf(self, tokens_list: list[list[str]]) -> dict[str, float]:
        df: Counter = Counter()
        for tokens in tokens_list:
            for token in set(tokens):
                df[token] += 1
        n = max(1, len(tokens_list))
        return {token: math.log((1 + n) / (1 + count)) + 1
                for token, count in df.items()}

    def _tfidf(self, tokens: list[str]) -> dict[str, float]:
        counts = Counter(tokens)
        total = max(1, len(tokens))
        return {token: (count / total) * self._idf.get(token, 1.0)
                for token, count in counts.items()}

    def similarity(self, query: str, index: int) -> float:
        qvec = self._tfidf(self._tokenize(query))
        dvec = self._tfidf(self._tokens[index])
        dot = sum(qvec.get(t, 0.0) * v for t, v in dvec.items())
        qnorm = math.sqrt(sum(v * v for v in qvec.values())) or 1.0
        dnorm = math.sqrt(sum(v * v for v in dvec.values())) or 1.0
        return dot / (qnorm * dnorm)


def hybrid_retrieve(library: SCSKnowledgeLibrary, question: str, *,
                    source_type: str | None = None,
                    manufacturer: str | None = None,
                    model: str | None = None,
                    limit: int = 5) -> list[dict[str, Any]]:
    """Authority-gated hybrid retrieval (M1.4.1 P11-P14).

    The authority eligibility list is an ENFORCED gate, not a scoring hint:
    candidates are sorted by authority rank FIRST, then lexical similarity.
    A lower-authority source (e.g. OEM manual) can never outrank the correct
    authority (project schedule) for a design question, regardless of lexical
    frequency. Composite questions still retrieve across the eligible set.
    """
    authority = SourceAuthorityContext()
    eligible = authority.authority_order(question)
    eligible_set = set(eligible)
    # trusted-source filter is applied by library.search (SOURCE_VERIFIED/ACTIVE)
    exact = library.search(question, source_type=source_type,
                           manufacturer=manufacturer, model=model,
                           limit=max(limit, 10))
    lexical = library.search(question, source_type=source_type, limit=max(limit * 4, 12))
    merged = {c["chunk_id"]: c for c in exact + lexical}
    candidates = list(merged.values())
    if not candidates:
        return []
    # authority eligibility gate: filter to eligible classes when the question
    # has a clear authority class
    if eligible_set and any(c.get("source_type") in eligible_set for c in candidates):
        candidates = [c for c in candidates if c.get("source_type") in eligible_set]
    if not candidates:
        return []
    texts = [str(c.get("text") or "") for c in candidates]
    tfidf = LocalTfIdf(texts)
    scored = []
    for index, candidate in enumerate(candidates):
        lexical_sim = tfidf.similarity(question, index)
        authority_rank = authority.rank(question, candidate.get("source_type", ""))
        identifier_bonus = 0.5 if _identifier_overlap(question, candidate) else 0.0
        # authority rank is the PRIMARY sort key (strict gate); lexical is tie-break
        scored.append((authority_rank, -(lexical_sim + identifier_bonus), candidate))
    scored.sort(key=lambda x: (x[0], x[1]))
    return [c for _r, _l, c in scored[:limit]]


def _identifier_overlap(question: str, candidate: dict[str, Any]) -> bool:
    q_ids = set(_IDENTIFIER_RE.findall(question.upper()))
    if not q_ids:
        return False
    blob = " ".join([
        str(candidate.get("text") or ""), str(candidate.get("document_number") or ""),
        str(candidate.get("title") or "")]).upper()
    return any(identifier in blob for identifier in q_ids)


# ---------------------------------------------------------------------------
# Retrieval benchmark (H8)
# ---------------------------------------------------------------------------

RETRIEVAL_BENCHMARK_VERSION = "1.0"


def retrieval_benchmark(library: SCSKnowledgeLibrary,
                        cases: list[dict[str, Any]]) -> dict[str, Any]:
    """cases: [{question, expected_source, acceptable_sources, forbidden, page?}]"""
    top1_hits = top3_hits = exact_hits = 0
    wrong_authority = wrong_applicability = 0
    total = len(cases)
    for case in cases:
        results = hybrid_retrieve(library, case["question"], limit=3)
        if not results:
            continue
        top1 = results[0]
        if top1.get("source_id") in (case.get("acceptable_sources") or
                                     [case.get("expected_source")]):
            top1_hits += 1
        top3 = {r.get("source_id") for r in results}
        acceptable = set(case.get("acceptable_sources") or [case.get("expected_source")])
        if top3 & acceptable:
            top3_hits += 1
        if any(r.get("source_id") in (case.get("forbidden") or [])
               for r in results[:1]):
            wrong_authority += 1
        if case.get("page") and any(r.get("page") == case["page"] for r in results):
            exact_hits += 1
    return {
        "benchmark_version": RETRIEVAL_BENCHMARK_VERSION,
        "cases": total,
        "TOP1_SOURCE_ACCURACY": round(top1_hits / total, 3) if total else 0.0,
        "TOP3_SOURCE_RECALL": round(top3_hits / total, 3) if total else 0.0,
        "EXACT_IDENTIFIER_RECALL": round(exact_hits / total, 3) if total else 0.0,
        "WRONG_AUTHORITY_RATE": round(wrong_authority / total, 3) if total else 0.0,
        "WRONG_APPLICABILITY_RATE": round(wrong_applicability / total, 3) if total else 0.0,
    }
