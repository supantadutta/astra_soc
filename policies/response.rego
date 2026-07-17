# ASTRASOC response-action policy (Open Policy Agent / Rego).
#
# This is the OPA-native equivalent of the built-in Python policy engine
# (apps/api/astrasoc/services/policy/engine.py). Point ASTRASOC_OPA_URL at an OPA
# instance loaded with this policy to evaluate response actions externally; the
# input/decision shape is identical, so the response gateway is unchanged.
#
# Input:
#   { "action": "isolate_endpoint", "asset_criticality": "high",
#     "confidence": 0.86, "evidence_count": 2, "reversible": true,
#     "blast_radius": 1 }
#
# Decision: data.astrasoc.response.decision -> "allow" | "deny" | "require_approval"

package astrasoc.response

import future.keywords.if
import future.keywords.in

default decision := "require_approval"

# --- Deny rules (highest precedence) --------------------------------------
deny if input.confidence < 0.5
deny if input.evidence_count < 1

# --- Auto-allow (safe, high-confidence, reversible, non-critical) ----------
allow if {
    input.reversible == true
    input.confidence >= 0.9
    input.asset_criticality in {"info", "low", "medium"}
}

allow if {
    input.action in {"increase_monitoring", "create_ticket", "notify_team"}
    input.confidence >= 0.7
}

# --- Require approval ------------------------------------------------------
needs_approval if input.asset_criticality in {"high", "critical"}
needs_approval if input.reversible == false
needs_approval if input.blast_radius > 5
needs_approval if input.confidence < 0.7

# --- Resolution: deny > require_approval > allow ---------------------------
decision := "deny" if deny
decision := "require_approval" if {
    not deny
    needs_approval
}
decision := "allow" if {
    not deny
    not needs_approval
    allow
}

approver_role := "incident_commander" if input.asset_criticality in {"high", "critical"}
approver_role := "soc_manager" if input.reversible == false
