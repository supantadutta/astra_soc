"""Knowledge base and memory models (curated retrieval)."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import GUID, Base
from .base import TenantMixin, TimestampMixin, UUIDMixin
from .enums import DataClassification


class KnowledgeDocument(UUIDMixin, TenantMixin, TimestampMixin, Base):
    """A curated document. ``scope`` names the memory partition it belongs to.

    Secrets are never stored here or in chunks/embeddings — ingestion runs a
    secret scrub first.
    """

    __tablename__ = "knowledge_documents"

    title: Mapped[str] = mapped_column(String(300))
    scope: Mapped[str] = mapped_column(String(40), default="tenant_knowledge", index=True)
    # incident_memory | tenant_knowledge | global_knowledge | playbook_knowledge
    # | detection_knowledge | threat_intel_knowledge
    body: Mapped[str] = mapped_column(Text, default="")
    classification: Mapped[str] = mapped_column(String(20), default=DataClassification.INTERNAL.value)
    # Provenance.
    source: Mapped[str] = mapped_column(String(200), default="")
    author: Mapped[str] = mapped_column(String(120), default="")
    trust_score: Mapped[float] = mapped_column(Float, default=0.7)
    version: Mapped[str] = mapped_column(String(20), default="1.0.0")
    accessed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    tags: Mapped[list] = mapped_column(default=list)
    is_global: Mapped[bool] = mapped_column(Boolean, default=False)

    chunks: Mapped[list[KnowledgeChunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class KnowledgeChunk(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_chunks"

    document_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True
    )
    scope: Mapped[str] = mapped_column(String(40), index=True)
    ordinal: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text)
    # Lightweight lexical vector for the demo profile (term-frequency map). In
    # production this is replaced by a pgvector embedding column.
    lexical_vector: Mapped[dict] = mapped_column(default=dict)
    classification: Mapped[str] = mapped_column(String(20), default=DataClassification.INTERNAL.value)

    document: Mapped[KnowledgeDocument] = relationship(back_populates="chunks")
