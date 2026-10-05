"""Retrieval-Augmented Generation over the environmental knowledge base.

Documents in data/knowledge_base/*.md are chunked by section and indexed together with every
structured standard record. Retrieval uses TF-IDF vectors with cosine similarity (an in-process
vector store). The interface (search / ask) is storage-agnostic and can be swapped for
pgvector, ChromaDB, Qdrant or FAISS embeddings without changing the agents.
"""
from __future__ import annotations

import re

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from ..config import KB_DIR
from . import llm
from .compliance import limit_text
from .standards import all_standards

_INDEX: dict = {}


def _chunks() -> list[dict]:
    out = []
    for f in sorted(KB_DIR.glob("*.md")):
        text = f.read_text(encoding="utf-8")
        title = text.splitlines()[0].lstrip("# ").strip()
        parts = re.split(r"\n(?=## )", text)
        for p in parts:
            head = p.splitlines()[0].lstrip("# ").strip()
            body = "\n".join(p.splitlines()[1:]).strip()
            if body:
                out.append({"doc": f.name, "title": title, "section": head, "text": body})
    for s in all_standards():
        out.append({"doc": s.get("source_doc"), "title": s.get("standard_name"), "section": s.get("section"),
                    "standard_id": s["id"],
                    "text": (f"Standard record {s['id']}: {s.get('standard_name')}. Parameter {s['parameter']}. "
                             f"Limit {limit_text(s)}. Averaging period {s.get('averaging_period')}. "
                             f"Applies to {', '.join(s.get('zones') or s.get('water_classes') or [])}. "
                             f"Version {s.get('version')}. Basis {s.get('basis')}. {s.get('note', '')}")})
    return out


def build_index(force: bool = False) -> None:
    if _INDEX and not force:
        return
    chunks = _chunks()
    vec = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, stop_words="english")
    mat = vec.fit_transform([f"{c['title']} {c['section']} {c['text']}" for c in chunks])
    _INDEX.update(chunks=chunks, vec=vec, mat=mat)


def search(query: str, k: int = 5) -> list[dict]:
    build_index()
    q = _INDEX["vec"].transform([query])
    sims = cosine_similarity(q, _INDEX["mat"]).ravel()
    best = sims.argsort()[::-1][:k]
    return [{**_INDEX["chunks"][i], "score": round(float(sims[i]), 4)} for i in best if sims[i] > 0]


def supporting_text(std: dict) -> dict | None:
    """Return the knowledge-base section that backs a structured standard record."""
    build_index()
    for c in _INDEX["chunks"]:
        sec = std.get("section") or ""
        if c["doc"] == std.get("source_doc") and "standard_id" not in c and (c["section"] == sec or sec.startswith(c["section"])):
            return c
    hits = [h for h in search(f"{std.get('standard_name')} {std.get('section')} {std.get('parameter')}", 10) if "standard_id" not in h]
    return hits[0] if hits else None


def ask(question: str, alert: dict | None = None) -> dict:
    """Answer a question about standards. If an alert is given, return the exact standard it used."""
    if alert and alert.get("standard_ref"):
        std = alert["standard_ref"]
        sup = supporting_text(std)
        answer = (f"Alert {alert['id']} used {std.get('standard_name')} ({std.get('id')}), {std.get('section')}: "
                  f"{std.get('parameter')} limit {limit_text(std)} over a {std.get('averaging_period')} averaging period. "
                  f"Version: {std.get('version')}.")
        if std.get("basis") != "regulatory":
            answer += f" Note: this reference is a {std.get('basis', '').replace('_', ' ')}, not a legal limit."
        return {"answer": answer, "mode": "alert_lookup", "standard": std,
                "source_document": std.get("source_doc"), "section": std.get("section"),
                "applicable_limit": limit_text(std), "averaging_period": std.get("averaging_period"), "unit": std.get("unit"),
                "supporting_text": sup["text"] if sup else None, "citations": [sup] if sup else []}
    hits = search(question, 5)
    if not hits:
        return {"answer": "No matching section was found in the configured knowledge base.", "citations": [], "mode": "retrieval"}
    context = "\n\n".join(f"[{i+1}] {h['title']} — {h['section']}: {h['text']}" for i, h in enumerate(hits))
    gen = llm.generate(
        "You answer questions about environmental standards using ONLY the numbered context passages. "
        "Cite passages as [n]. If the context does not contain the answer, say so. Never invent limits.",
        f"Question: {question}\n\nContext:\n{context}")
    top = hits[0]
    answer = gen or f"From {top['title']} — {top['section']}: {top['text'][:600]}"
    std_hit = next((h for h in hits if h.get("standard_id")), None)
    return {"answer": answer, "mode": "llm_rag" if gen else "extractive", "citations": hits,
            "source_document": top["doc"], "section": top["section"],
            "standard_id": std_hit.get("standard_id") if std_hit else None}
