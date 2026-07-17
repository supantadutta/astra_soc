# Data Flow

```
Connector / generator ─▶ SecurityEvent (OCSF-normalized, scoped)
        │
        ▼  deterministic detection matcher
     Alert ──▶ correlation ──▶ Incident (fuses alerts, entities, evidence)
        │                          │
        │                          ├─ Entities + EntityRelationship (graph)
        │                          ├─ Evidence (fact | inference | assumption | …)
        │                          ├─ TimelineEntry
        │                          └─ Hypothesis (+ supporting/contradicting/missing)
        ▼
  Investigation (coordinator → agents via tool broker → model gateway)
        │  evidence-first claims → hypotheses + MODEL_INFERENCE evidence
        ▼
  Recommended actions ──▶ ResponseAction
        │  schema → evidence → confidence → criticality → blast radius
        │  → RBAC → policy → approval → dry-run → execute → verify → rollback
        ▼
  Connector write adapter (LIVE) / simulation (DEMO) ──▶ verification
        │
        ▼
  AuditEvent (hash-chained) · Report · Notification · Feedback → learning
```

Real-time: every stage publishes to the event bus; the browser receives updates
via SSE (`/api/v1/stream`) filtered by mode scope. No polling, no full refresh.
