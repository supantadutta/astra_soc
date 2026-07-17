"""Adapter registry mapping connector kind -> adapter class.

Concrete adapters mostly differ in auth style, health path and category. Where a
vendor needs bespoke logic, subclass :class:`ConnectorAdapter`. Every kind in
the seed catalog resolves to an adapter so health checks and (mock) actions work
uniformly.
"""
from __future__ import annotations

from ...models import Connector
from ...models.enums import ConnectorCategory
from .base import ConnectorAdapter


def _adapter(category: str, health_path: str = "/health", auth: str = "bearer"):
    return type(
        f"Adapter_{category}",
        (ConnectorAdapter,),
        {"category": category, "health_path": health_path, "auth_style": auth},
    )


# kind -> (category, health_path, auth_style)
_SPEC: dict[str, tuple[str, str, str]] = {
    # SIEM
    "crowdstrike_logscale": (ConnectorCategory.SIEM.value, "/api/v1/status", "bearer"),
    "splunk": (ConnectorCategory.SIEM.value, "/services/server/info", "bearer"),
    "microsoft_sentinel": (ConnectorCategory.SIEM.value, "/", "bearer"),
    "elastic": (ConnectorCategory.SIEM.value, "/_cluster/health", "bearer"),
    "generic_rest_siem": (ConnectorCategory.SIEM.value, "/api/v1/events", "apikey_header"),
    "generic_syslog": (ConnectorCategory.SIEM.value, "/health", "none"),
    # EDR / NDR
    "crowdstrike_falcon": (ConnectorCategory.EDR.value, "/devices/queries/devices/v1", "bearer"),
    "microsoft_defender": (ConnectorCategory.EDR.value, "/api/machines", "bearer"),
    "vectra": (ConnectorCategory.NDR.value, "/api/v2/health", "apikey_header"),
    "stellar_cyber": (ConnectorCategory.NDR.value, "/connect/api/v1/health", "bearer"),
    "generic_edr": (ConnectorCategory.EDR.value, "/api/v1/health", "apikey_header"),
    # Identity
    "entra_id": (ConnectorCategory.IDENTITY.value, "/v1.0/organization", "bearer"),
    "active_directory": (ConnectorCategory.IDENTITY.value, "/health", "bearer"),
    "keycloak": (ConnectorCategory.IDENTITY.value, "/realms/master", "bearer"),
    "generic_ldap": (ConnectorCategory.IDENTITY.value, "/health", "none"),
    # Threat intel
    "misp": (ConnectorCategory.THREAT_INTEL.value, "/servers/getVersion", "apikey_header"),
    "virustotal": (ConnectorCategory.THREAT_INTEL.value, "/api/v3/metadata", "apikey_header"),
    "taxii": (ConnectorCategory.THREAT_INTEL.value, "/taxii2/", "bearer"),
    "generic_stix_taxii": (ConnectorCategory.THREAT_INTEL.value, "/taxii2/", "bearer"),
    # ITSM / comms
    "servicenow": (ConnectorCategory.ITSM.value, "/api/now/table/sys_user?sysparm_limit=1", "basic"),
    "jira": (ConnectorCategory.ITSM.value, "/rest/api/3/myself", "basic"),
    "slack": (ConnectorCategory.COMMS.value, "/api/auth.test", "bearer"),
    "microsoft_teams": (ConnectorCategory.COMMS.value, "/v1.0/me", "bearer"),
    "email_webhook": (ConnectorCategory.COMMS.value, "/health", "apikey_header"),
    # Cloud
    "aws": (ConnectorCategory.CLOUD.value, "/health", "bearer"),
    "azure": (ConnectorCategory.CLOUD.value, "/health", "bearer"),
    "gcp": (ConnectorCategory.CLOUD.value, "/health", "bearer"),
    "k8s_audit": (ConnectorCategory.CLOUD.value, "/healthz", "bearer"),
}


def list_connector_kinds() -> list[str]:
    return list(_SPEC.keys())


def get_adapter(connector: Connector, http_client=None) -> ConnectorAdapter:
    spec = _SPEC.get(connector.kind, (ConnectorCategory.SIEM.value, "/health", "bearer"))
    cls = _adapter(*spec)
    return cls(connector, http_client=http_client)
