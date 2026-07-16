"""Enumerations used across the domain models.

Stored as their string ``value`` in the database for portability and
human-readable audit trails.
"""
from __future__ import annotations

import enum


class DataScope(str, enum.Enum):
    """Whether a row belongs to simulated demo data or real live data.

    This is the backbone of demo/live separation: every operational row carries
    a scope and queries are filtered by the current mode. Demo and live rows
    never mix.
    """

    DEMO = "DEMO"
    LIVE = "LIVE"


class Severity(str, enum.Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IncidentStatus(str, enum.Enum):
    NEW = "new"
    TRIAGED = "triaged"
    INVESTIGATING = "investigating"
    CONTAINED = "contained"
    RESOLVED = "resolved"
    CLOSED = "closed"
    FALSE_POSITIVE = "false_positive"


class AlertStatus(str, enum.Enum):
    NEW = "new"
    ACKNOWLEDGED = "acknowledged"
    INVESTIGATING = "investigating"
    ESCALATED = "escalated"
    SUPPRESSED = "suppressed"
    CLOSED = "closed"


class EntityKind(str, enum.Enum):
    USER = "user"
    HOST = "host"
    IP = "ip"
    DOMAIN = "domain"
    FILE = "file"
    PROCESS = "process"
    ACCOUNT = "account"
    MAILBOX = "mailbox"
    CLOUD_RESOURCE = "cloud_resource"
    VULNERABILITY = "vulnerability"


class EvidenceKind(str, enum.Enum):
    """Epistemic status of a piece of information in an investigation.

    The distinction is enforced through the pipeline: only CONFIRMED_FACT
    evidence can satisfy a response action's evidence requirement, and AI
    output is always labelled MODEL_INFERENCE until an analyst promotes it.
    """

    CONFIRMED_FACT = "confirmed_fact"
    MODEL_INFERENCE = "model_inference"
    ANALYST_CONCLUSION = "analyst_conclusion"
    ASSUMPTION = "assumption"
    MISSING_EVIDENCE = "missing_evidence"
    RECOMMENDED_ACTION = "recommended_action"
    EXECUTED_ACTION = "executed_action"


class AgentRunStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    BUDGET_EXCEEDED = "budget_exceeded"
    CANCELLED = "cancelled"


class ToolScope(str, enum.Enum):
    READ_ONLY = "read_only"
    RESPONSE = "response"  # production-changing


class ProviderKind(str, enum.Enum):
    OPENAI = "openai"
    AZURE_OPENAI = "azure_openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    BEDROCK = "bedrock"
    VLLM = "vllm"
    OLLAMA = "ollama"
    OPENAI_COMPATIBLE = "openai_compatible"
    SIMULATED = "simulated"  # built-in deterministic fallback


class HealthState(str, enum.Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    NOT_CONFIGURED = "not_configured"
    UNKNOWN = "unknown"


class ApprovalStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    AUTO_APPROVED = "auto_approved"


class ActionStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    DRY_RUN = "dry_run"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    VERIFIED = "verified"
    VERIFY_FAILED = "verify_failed"
    ROLLED_BACK = "rolled_back"
    REJECTED = "rejected"
    BLOCKED_BY_POLICY = "blocked_by_policy"


class WorkflowStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PolicyEffect(str, enum.Enum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


class ConnectorCategory(str, enum.Enum):
    SIEM = "siem"
    EDR = "edr"
    NDR = "ndr"
    IDENTITY = "identity"
    THREAT_INTEL = "threat_intel"
    ITSM = "itsm"
    COMMS = "comms"
    CLOUD = "cloud"


class FeedbackKind(str, enum.Enum):
    CORRECT = "correct"
    INCORRECT = "incorrect"
    PARTIALLY_CORRECT = "partially_correct"
    HELPFUL = "helpful"
    NOT_HELPFUL = "not_helpful"
    MISSING_EVIDENCE = "missing_evidence"
    WRONG_SEVERITY = "wrong_severity"
    WRONG_ATTACK_MAPPING = "wrong_attack_mapping"
    UNSAFE_RECOMMENDATION = "unsafe_recommendation"


class DataClassification(str, enum.Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"
