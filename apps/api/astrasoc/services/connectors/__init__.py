"""Connector framework: typed adapters, health checks, mock servers."""
from .registry import get_adapter, list_connector_kinds

__all__ = ["get_adapter", "list_connector_kinds"]
