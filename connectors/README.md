# Connectors

Connector **definitions** (catalog) live in
`apps/api/astrasoc/seed/catalog.py`; the **framework, adapters, health checks and
mock server** live in `apps/api/astrasoc/services/connectors/`. This directory
holds connector-level artifacts and is the extension point for out-of-tree or
Go-based connectors that speak the same typed adapter contract.

See [../docs/INTEGRATION.md](../docs/INTEGRATION.md).
