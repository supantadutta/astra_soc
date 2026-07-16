"""Domain models. Importing this package registers every table on ``Base``."""
from __future__ import annotations

from .ai import (
    Agent,
    AgentRun,
    AgentVersion,
    ModelDeployment,
    ModelProvider,
    ModelRoute,
    PromptTemplate,
    Tool,
    ToolExecution,
)
from .connector import Connector, ConnectorCredentialReference, ConnectorHealth
from .detection import DetectionRule, ThreatIndicator
from .identity import APIKey, Permission, Role, Session, Tenant, User, UserRole
from .knowledge import KnowledgeChunk, KnowledgeDocument
from .learning import AnalystFeedback, EvaluationDataset, EvaluationRun
from .platform import AuditEvent, Notification, Report, SystemSetting
from .response import (
    ApprovalRequest,
    Playbook,
    PlaybookVersion,
    PolicyDecision,
    ResponseAction,
    WorkflowRun,
)
from .security import (
    Alert,
    Entity,
    EntityRelationship,
    Evidence,
    Hypothesis,
    Incident,
    IncidentAlert,
    SecurityEvent,
    TimelineEntry,
)

__all__ = [
    "Tenant", "User", "Role", "Permission", "UserRole", "Session", "APIKey",
    "Connector", "ConnectorCredentialReference", "ConnectorHealth",
    "SecurityEvent", "Alert", "Incident", "IncidentAlert", "Entity",
    "EntityRelationship", "Evidence", "TimelineEntry", "Hypothesis",
    "Agent", "AgentVersion", "AgentRun", "Tool", "ToolExecution",
    "ModelProvider", "ModelDeployment", "ModelRoute", "PromptTemplate",
    "KnowledgeDocument", "KnowledgeChunk",
    "Playbook", "PlaybookVersion", "WorkflowRun", "ResponseAction",
    "ApprovalRequest", "PolicyDecision",
    "DetectionRule", "ThreatIndicator",
    "AnalystFeedback", "EvaluationDataset", "EvaluationRun",
    "Report", "AuditEvent", "Notification", "SystemSetting",
]
