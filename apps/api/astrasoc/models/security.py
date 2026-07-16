"""Security operations domain: events, alerts, incidents, entities, evidence."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import GUID, Base
from .base import ScopeMixin, TenantMixin, TimestampMixin, UUIDMixin
from .enums import (
    AlertStatus,
    EvidenceKind,
    IncidentStatus,
    Severity,
)


class SecurityEvent(UUIDMixin, TenantMixin, ScopeMixin, TimestampMixin, Base):
    """A normalized (OCSF-aligned) security event ingested from a source."""

    __tablename__ = "security_events"
    __table_args__ = (
        Index("ix_events_tenant_scope_ts", "tenant_id", "data_scope", "event_time"),
    )

    source: Mapped[str] = mapped_column(String(80), index=True)
    connector_id: Mapped[uuid.UUID | None] = mapped_column(GUID, nullable=True)
    event_time: Mapped[datetime] = mapped_column(index=True)
    # OCSF class + activity (e.g. 4001 Network Activity, 1001 File System).
    ocsf_class_uid: Mapped[int] = mapped_column(Integer, default=0)
    ocsf_category: Mapped[str] = mapped_column(String(60), default="")
    activity: Mapped[str] = mapped_column(String(120), default="")
    severity: Mapped[str] = mapped_column(String(16), default=Severity.INFO.value)
    # The normalized OCSF-style payload plus the original raw event.
    ocsf: Mapped[dict] = mapped_column(default=dict)
    raw: Mapped[dict] = mapped_column(default=dict)
    # Denormalized observables for fast correlation.
    src_ip: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    dst_ip: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    user_name: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    host_name: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)


class Alert(UUIDMixin, TenantMixin, ScopeMixin, TimestampMixin, Base):
    """A deterministic detection firing. Alerts correlate into incidents."""

    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alerts_tenant_scope_status", "tenant_id", "data_scope", "status"),
    )

    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(80), index=True)
    detection_rule_id: Mapped[uuid.UUID | None] = mapped_column(GUID, nullable=True)
    severity: Mapped[str] = mapped_column(String(16), default=Severity.MEDIUM.value, index=True)
    status: Mapped[str] = mapped_column(String(20), default=AlertStatus.NEW.value, index=True)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    # MITRE ATT&CK technique IDs, e.g. ["T1078", "T1110.003"].
    attack_techniques: Mapped[list] = mapped_column(default=list)
    # Observables extracted from the triggering events.
    observables: Mapped[dict] = mapped_column(default=dict)
    dedup_key: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(GUID, nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(nullable=True)
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("incidents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_ids: Mapped[list] = mapped_column(default=list)

    incident: Mapped[Incident | None] = relationship(back_populates="alerts")


class Incident(UUIDMixin, TenantMixin, ScopeMixin, TimestampMixin, Base):
    """A unified case fusing correlated alerts, entities and evidence."""

    __tablename__ = "incidents"
    __table_args__ = (
        Index("ix_incidents_tenant_scope_status", "tenant_id", "data_scope", "status"),
    )

    key: Mapped[str] = mapped_column(String(24), index=True)  # e.g. INC-000123
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[str] = mapped_column(String(16), default=Severity.MEDIUM.value, index=True)
    status: Mapped[str] = mapped_column(String(20), default=IncidentStatus.NEW.value, index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    business_risk: Mapped[float] = mapped_column(Float, default=0.0)  # 0-100
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(GUID, nullable=True)
    scenario_key: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    # SLA tracking.
    sla_ack_due: Mapped[datetime | None] = mapped_column(nullable=True)
    sla_resolve_due: Mapped[datetime | None] = mapped_column(nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(nullable=True)
    investigated_at: Mapped[datetime | None] = mapped_column(nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(nullable=True)
    # ATT&CK coverage and denormalized entity summary.
    attack_tactics: Mapped[list] = mapped_column(default=list)
    attack_techniques: Mapped[list] = mapped_column(default=list)
    affected_users: Mapped[list] = mapped_column(default=list)
    affected_hosts: Mapped[list] = mapped_column(default=list)
    related_ips: Mapped[list] = mapped_column(default=list)
    related_domains: Mapped[list] = mapped_column(default=list)
    tags: Mapped[list] = mapped_column(default=list)

    alerts: Mapped[list[Alert]] = relationship(back_populates="incident")
    evidence: Mapped[list[Evidence]] = relationship(
        back_populates="incident", cascade="all, delete-orphan"
    )
    timeline: Mapped[list[TimelineEntry]] = relationship(
        back_populates="incident", cascade="all, delete-orphan"
    )
    hypotheses: Mapped[list[Hypothesis]] = relationship(
        back_populates="incident", cascade="all, delete-orphan"
    )


class IncidentAlert(UUIDMixin, TimestampMixin, Base):
    """Explicit join with correlation metadata (why an alert joined a case)."""

    __tablename__ = "incident_alerts"

    incident_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("incidents.id", ondelete="CASCADE"), index=True
    )
    alert_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("alerts.id", ondelete="CASCADE"), index=True
    )
    correlation_reason: Mapped[str] = mapped_column(String(200), default="")
    correlation_score: Mapped[float] = mapped_column(Float, default=0.0)


class Entity(UUIDMixin, TenantMixin, ScopeMixin, TimestampMixin, Base):
    """An enriched observable: user, host, IP, domain, file, vulnerability, ..."""

    __tablename__ = "entities"
    __table_args__ = (
        Index("ix_entities_tenant_scope_kind_value", "tenant_id", "data_scope", "kind", "value"),
    )

    kind: Mapped[str] = mapped_column(String(24), index=True)
    value: Mapped[str] = mapped_column(String(400), index=True)
    display_name: Mapped[str] = mapped_column(String(300), default="")
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    criticality: Mapped[str] = mapped_column(String(16), default=Severity.LOW.value)
    is_internal: Mapped[bool] = mapped_column(Boolean, default=True)
    # Enrichment payload from connectors/threat-intel (labelled by provenance).
    enrichment: Mapped[dict] = mapped_column(default=dict)
    first_seen: Mapped[datetime | None] = mapped_column(nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(nullable=True)


class EntityRelationship(UUIDMixin, TenantMixin, ScopeMixin, TimestampMixin, Base):
    """A directed edge in the entity/attack graph."""

    __tablename__ = "entity_relationships"

    src_entity_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("entities.id", ondelete="CASCADE"), index=True
    )
    dst_entity_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("entities.id", ondelete="CASCADE"), index=True
    )
    relationship_type: Mapped[str] = mapped_column(String(60))  # authenticated_to, connected_to...
    incident_id: Mapped[uuid.UUID | None] = mapped_column(GUID, nullable=True, index=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    attributes: Mapped[dict] = mapped_column(default=dict)


class Evidence(UUIDMixin, TenantMixin, ScopeMixin, TimestampMixin, Base):
    """A discrete, citable piece of investigation information.

    ``kind`` records epistemic status (fact vs inference vs assumption). A
    response action can only be justified by CONFIRMED_FACT evidence.
    """

    __tablename__ = "evidence"
    __table_args__ = (Index("ix_evidence_incident_kind", "incident_id", "kind"),)

    incident_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("incidents.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(24), default=EvidenceKind.CONFIRMED_FACT.value)
    title: Mapped[str] = mapped_column(String(300))
    content: Mapped[str] = mapped_column(Text, default="")
    # Provenance: which source/tool/event/model produced this.
    source: Mapped[str] = mapped_column(String(120), default="")
    source_ref: Mapped[str | None] = mapped_column(String(300), nullable=True)
    produced_by: Mapped[str] = mapped_column(String(120), default="")  # analyst | agent | tool
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    event_ids: Mapped[list] = mapped_column(default=list)
    entity_ids: Mapped[list] = mapped_column(default=list)
    attack_techniques: Mapped[list] = mapped_column(default=list)
    # Cryptographic hash of the content for tamper-evidence.
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    incident: Mapped[Incident] = relationship(back_populates="evidence")


class TimelineEntry(UUIDMixin, TenantMixin, ScopeMixin, TimestampMixin, Base):
    __tablename__ = "timeline_entries"
    __table_args__ = (Index("ix_timeline_incident_ts", "incident_id", "occurred_at"),)

    incident_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("incidents.id", ondelete="CASCADE"), index=True
    )
    occurred_at: Mapped[datetime] = mapped_column(index=True)
    title: Mapped[str] = mapped_column(String(300))
    detail: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(40), default="event")  # event|action|note|agent
    actor: Mapped[str] = mapped_column(String(120), default="")
    evidence_id: Mapped[uuid.UUID | None] = mapped_column(GUID, nullable=True)
    attack_techniques: Mapped[list] = mapped_column(default=list)

    incident: Mapped[Incident] = relationship(back_populates="timeline")


class Hypothesis(UUIDMixin, TenantMixin, ScopeMixin, TimestampMixin, Base):
    """An investigation hypothesis with supporting/contradicting evidence.

    Backs the claim-evidence graph. Alternative hypotheses and the evidence
    still missing to confirm/refute are first-class.
    """

    __tablename__ = "hypotheses"

    incident_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("incidents.id", ondelete="CASCADE"), index=True
    )
    statement: Mapped[str] = mapped_column(Text)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    status: Mapped[str] = mapped_column(String(24), default="open")  # open|supported|refuted
    supporting_evidence_ids: Mapped[list] = mapped_column(default=list)
    contradicting_evidence_ids: Mapped[list] = mapped_column(default=list)
    missing_evidence: Mapped[list] = mapped_column(default=list)
    attack_techniques: Mapped[list] = mapped_column(default=list)
    produced_by: Mapped[str] = mapped_column(String(120), default="agent")

    incident: Mapped[Incident] = relationship(back_populates="hypotheses")
