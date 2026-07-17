# Database

## Engines
SQLite (demo, zero-dependency) or PostgreSQL (dev/prod). The same schema runs on
both via portable types: `GUID` (native UUID on PG, CHAR(36) on SQLite), a JSON
type (JSONB on PG), and `TZDateTime` (tz-aware even on SQLite).

## Domain models (45 tables)
Tenant, User, Role, Permission, UserRole, Session, APIKey, Connector,
ConnectorCredentialReference, ConnectorHealth, SecurityEvent, Alert, Incident,
IncidentAlert, Entity, EntityRelationship, Evidence, TimelineEntry, Hypothesis,
Agent, AgentVersion, AgentRun, Tool, ToolExecution, ModelProvider,
ModelDeployment, ModelRoute, PromptTemplate, KnowledgeDocument, KnowledgeChunk,
Playbook, PlaybookVersion, WorkflowRun, ResponseAction, ApprovalRequest,
PolicyDecision, DetectionRule, ThreatIndicator, AnalystFeedback,
EvaluationDataset, EvaluationRun, Report, AuditEvent, Notification,
SystemSetting.

All use UUID PKs, created/updated timestamps, tenant scoping where relevant, a
`data_scope` (DEMO/LIVE) on operational rows, and appropriate indexes.

## Migrations (Alembic)
```bash
cd apps/api
alembic revision --autogenerate -m "change"   # generate
alembic upgrade head                           # apply
alembic downgrade -1                           # revert
```
The demo/test profiles auto-create tables from metadata on boot; production
should use Alembic. The initial migration creates all 45 tables and reverses
cleanly.

## Scoping
`data_scope` is the backbone of demo/live separation. `services/mode.current_scope`
returns the active scope; list/detail queries filter by it so the two data sets
never mix.
