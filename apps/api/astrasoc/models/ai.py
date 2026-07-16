"""AI subsystem: agents, tools, model providers/deployments/routes, prompts."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import GUID, Base
from .base import TenantMixin, TimestampMixin, UUIDMixin
from .enums import AgentRunStatus, HealthState, ProviderKind, ToolScope


class Agent(UUIDMixin, TimestampMixin, Base):
    """A bounded specialist agent definition (registry entry)."""

    __tablename__ = "agents"

    key: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    purpose: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Guardrails.
    tool_allowlist: Mapped[list] = mapped_column(default=list)
    max_execution_seconds: Mapped[int] = mapped_column(Integer, default=120)
    max_token_budget: Mapped[int] = mapped_column(Integer, default=40000)
    max_tool_calls: Mapped[int] = mapped_column(Integer, default=12)
    required_data_classification: Mapped[str] = mapped_column(String(20), default="internal")
    required_capability: Mapped[str] = mapped_column(String(40), default="deep_investigator")
    failure_policy: Mapped[str] = mapped_column(String(24), default="halt")  # halt|continue|retry
    retry_policy: Mapped[dict] = mapped_column(default=dict)
    input_schema: Mapped[dict] = mapped_column(default=dict)
    output_schema: Mapped[dict] = mapped_column(default=dict)
    evaluation_score: Mapped[float] = mapped_column(Float, default=0.0)
    current_version: Mapped[str] = mapped_column(String(20), default="1.0.0")

    versions: Mapped[list[AgentVersion]] = relationship(back_populates="agent")


class AgentVersion(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "agent_versions"
    __table_args__ = (UniqueConstraint("agent_id", "version", name="uq_agent_versions"),)

    agent_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[str] = mapped_column(String(20))
    prompt_template_id: Mapped[uuid.UUID | None] = mapped_column(GUID, nullable=True)
    config: Mapped[dict] = mapped_column(default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    changelog: Mapped[str] = mapped_column(Text, default="")

    agent: Mapped[Agent] = relationship(back_populates="versions")


class AgentRun(UUIDMixin, TenantMixin, TimestampMixin, Base):
    """A single bounded execution of an agent within a case workflow."""

    __tablename__ = "agent_runs"

    agent_key: Mapped[str] = mapped_column(String(60), index=True)
    agent_version: Mapped[str] = mapped_column(String(20), default="1.0.0")
    incident_id: Mapped[uuid.UUID | None] = mapped_column(GUID, nullable=True, index=True)
    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column(GUID, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default=AgentRunStatus.PENDING.value, index=True)
    data_scope: Mapped[str] = mapped_column(String(8), default="DEMO", index=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    # Budget accounting.
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    tool_calls_made: Mapped[int] = mapped_column(Integer, default=0)
    model_used: Mapped[str] = mapped_column(String(120), default="")
    provider_used: Mapped[str] = mapped_column(String(40), default="")
    input: Mapped[dict] = mapped_column(default=dict)
    output: Mapped[dict] = mapped_column(default=dict)  # evidence-first structured result
    steps: Mapped[list] = mapped_column(default=list)  # ordered trace of tool calls / reasoning
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    simulated: Mapped[bool] = mapped_column(Boolean, default=True)


class Tool(UUIDMixin, TimestampMixin, Base):
    """A registered tool the broker can expose to agents."""

    __tablename__ = "tools"

    key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[str] = mapped_column(String(20), default="1.0.0")
    scope: Mapped[str] = mapped_column(String(20), default=ToolScope.READ_ONLY.value, index=True)
    required_permission: Mapped[str] = mapped_column(String(80), default="tool:read")
    input_schema: Mapped[dict] = mapped_column(default=dict)
    output_schema: Mapped[dict] = mapped_column(default=dict)
    allowed_tenants: Mapped[list] = mapped_column(default=list)  # empty => all
    egress_allowlist: Mapped[list] = mapped_column(default=list)
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=60)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30)
    max_response_bytes: Mapped[int] = mapped_column(Integer, default=1_000_000)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_mcp: Mapped[bool] = mapped_column(Boolean, default=False)


class ToolExecution(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "tool_executions"

    tool_key: Mapped[str] = mapped_column(String(80), index=True)
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(GUID, nullable=True, index=True)
    incident_id: Mapped[uuid.UUID | None] = mapped_column(GUID, nullable=True, index=True)
    scope: Mapped[str] = mapped_column(String(20), default=ToolScope.READ_ONLY.value)
    data_scope: Mapped[str] = mapped_column(String(8), default="DEMO")
    input: Mapped[dict] = mapped_column(default=dict)
    output: Mapped[dict] = mapped_column(default=dict)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # HMAC signature over the result for tamper-evidence.
    result_signature: Mapped[str | None] = mapped_column(String(128), nullable=True)
    simulated: Mapped[bool] = mapped_column(Boolean, default=True)


class ModelProvider(UUIDMixin, TenantMixin, TimestampMixin, Base):
    """A configured LLM provider. Secrets are stored by reference only."""

    __tablename__ = "model_providers"

    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(30), default=ProviderKind.SIMULATED.value, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    base_url: Mapped[str | None] = mapped_column(String(400), nullable=True)
    region: Mapped[str | None] = mapped_column(String(60), nullable=True)
    # Reference into the secret manager, e.g. "vault://astrasoc/openai#api_key".
    secret_ref: Mapped[str | None] = mapped_column(String(300), nullable=True)
    data_classification_allowance: Mapped[str] = mapped_column(String(20), default="internal")
    # Guardrails / policy.
    private_only: Mapped[bool] = mapped_column(Boolean, default=False)
    allowed_geographies: Mapped[list] = mapped_column(default=list)
    daily_token_limit: Mapped[int] = mapped_column(Integer, default=0)  # 0 => unlimited
    monthly_cost_limit_usd: Mapped[float] = mapped_column(Float, default=0.0)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=60)
    max_retries: Mapped[int] = mapped_column(Integer, default=2)
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=120)
    fallback_priority: Mapped[int] = mapped_column(Integer, default=100)
    # Health / circuit breaker state.
    health: Mapped[str] = mapped_column(String(20), default=HealthState.UNKNOWN.value, index=True)
    last_health_check: Mapped[datetime | None] = mapped_column(nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    circuit_open_until: Mapped[datetime | None] = mapped_column(nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Usage metrics (running totals).
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    total_requests: Mapped[int] = mapped_column(Integer, default=0)

    deployments: Mapped[list[ModelDeployment]] = relationship(back_populates="provider")


class ModelDeployment(UUIDMixin, TimestampMixin, Base):
    """A specific model exposed by a provider, with capability tags + cost."""

    __tablename__ = "model_deployments"

    provider_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("model_providers.id", ondelete="CASCADE"), index=True
    )
    model_identifier: Mapped[str] = mapped_column(String(160))
    display_name: Mapped[str] = mapped_column(String(160), default="")
    capabilities: Mapped[list] = mapped_column(default=list)  # capability aliases
    context_window: Mapped[int] = mapped_column(Integer, default=128000)
    supports_tools: Mapped[bool] = mapped_column(Boolean, default=True)
    supports_vision: Mapped[bool] = mapped_column(Boolean, default=False)
    cost_input_per_1k: Mapped[float] = mapped_column(Float, default=0.0)
    cost_output_per_1k: Mapped[float] = mapped_column(Float, default=0.0)
    avg_latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    quality_score: Mapped[float] = mapped_column(Float, default=0.7)
    tool_reliability: Mapped[float] = mapped_column(Float, default=0.8)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    provider: Mapped[ModelProvider] = relationship(back_populates="deployments")


class ModelRoute(UUIDMixin, TenantMixin, TimestampMixin, Base):
    """Maps a capability alias to primary/fallback/verifier/shadow deployments."""

    __tablename__ = "model_routes"
    __table_args__ = (UniqueConstraint("tenant_id", "capability", name="uq_model_routes_cap"),)

    capability: Mapped[str] = mapped_column(String(40), index=True)
    primary_deployment_id: Mapped[uuid.UUID | None] = mapped_column(GUID, nullable=True)
    fallback_deployment_id: Mapped[uuid.UUID | None] = mapped_column(GUID, nullable=True)
    verifier_deployment_id: Mapped[uuid.UUID | None] = mapped_column(GUID, nullable=True)
    shadow_deployment_id: Mapped[uuid.UUID | None] = mapped_column(GUID, nullable=True)
    require_verification: Mapped[bool] = mapped_column(Boolean, default=False)
    max_data_classification: Mapped[str] = mapped_column(String(20), default="confidential")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class PromptTemplate(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "prompt_templates"

    key: Mapped[str] = mapped_column(String(80), index=True)
    version: Mapped[str] = mapped_column(String(20), default="1.0.0")
    description: Mapped[str] = mapped_column(Text, default="")
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    user_template: Mapped[str] = mapped_column(Text, default="")
    output_schema: Mapped[dict] = mapped_column(default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
