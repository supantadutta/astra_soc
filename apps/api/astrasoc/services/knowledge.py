"""Knowledge retrieval with tenant + RBAC + scope isolation.

The demo profile uses a lexical (term-frequency) retriever so there is no
external vector-DB dependency; production swaps ``KnowledgeChunk.lexical_vector``
for pgvector embeddings and the same query interface applies. Cross-tenant
retrieval is impossible: every query is filtered by tenant and (for non-global
scopes) never returns another tenant's rows. Secrets are scrubbed at ingest.
"""
from __future__ import annotations

import math
import re
import uuid
from collections import Counter

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import KnowledgeChunk, KnowledgeDocument
from .injection import apply_dlp

_WORD = re.compile(r"[a-z0-9]{2,}")


def _tokenize(text: str) -> list[str]:
    return _WORD.findall((text or "").lower())


def lexical_vector(text: str) -> dict[str, int]:
    return dict(Counter(_tokenize(text)))


def ingest_document(
    db: Session, tenant_id: uuid.UUID, *, title: str, body: str, scope: str,
    classification: str = "internal", source: str = "", author: str = "",
    is_global: bool = False, chunk_size: int = 500,
) -> KnowledgeDocument:
    # DLP scrub before anything is stored or indexed.
    clean_body, redactions = apply_dlp(body)
    doc = KnowledgeDocument(
        tenant_id=tenant_id, title=title, body=clean_body, scope=scope,
        classification=classification, source=source, author=author, is_global=is_global,
        tags=[], trust_score=0.7,
    )
    db.add(doc)
    db.flush()
    words = clean_body.split()
    for i in range(0, max(1, len(words)), chunk_size):
        chunk_text = " ".join(words[i:i + chunk_size])
        db.add(KnowledgeChunk(
            tenant_id=tenant_id, document_id=doc.id, scope=scope, ordinal=i // chunk_size,
            content=chunk_text, lexical_vector=lexical_vector(chunk_text),
            classification=classification,
        ))
    db.flush()
    return doc


def search(
    db: Session, tenant_id: uuid.UUID, query: str, *,
    scopes: list[str] | None = None, allowed_classifications: list[str] | None = None,
    limit: int = 8,
) -> list[dict]:
    """Retrieve chunks by lexical similarity, enforcing tenant/RBAC/scope."""
    q_vec = lexical_vector(query)
    if not q_vec:
        return []
    # Tenant isolation: this tenant's rows OR global-knowledge rows.
    stmt = select(KnowledgeChunk).join(
        KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id
    ).where(
        or_(KnowledgeChunk.tenant_id == tenant_id, KnowledgeDocument.is_global.is_(True))
    )
    if scopes:
        stmt = stmt.where(KnowledgeChunk.scope.in_(scopes))
    if allowed_classifications:
        stmt = stmt.where(KnowledgeChunk.classification.in_(allowed_classifications))
    chunks = db.execute(stmt.limit(500)).scalars().all()

    scored = []
    for ch in chunks:
        score = _cosine(q_vec, ch.lexical_vector or {})
        if score > 0:
            scored.append((score, ch))
    scored.sort(key=lambda x: x[0], reverse=True)
    results = []
    for score, ch in scored[:limit]:
        results.append({
            "chunk_id": str(ch.id), "document_id": str(ch.document_id), "scope": ch.scope,
            "score": round(score, 4), "content": ch.content[:600],
            "classification": ch.classification,
        })
    return results


def _cosine(a: dict[str, int], b: dict[str, int]) -> float:
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    dot = sum(a[t] * b[t] for t in common)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0
