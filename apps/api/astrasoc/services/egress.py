"""Outbound egress policy for connector and LLM-provider URLs.

Any URL an operator or tenant can configure is validated twice: when it is
saved (fast, literal checks) and immediately before each request (the hostname
is resolved and every resulting address is checked, which defeats DNS names
that point at forbidden ranges).

Always blocked: non-http(s) schemes, embedded credentials, link-local
addresses (including the 169.254.169.254 cloud-metadata endpoint),
unspecified/multicast/reserved ranges and well-known metadata hostnames.
Configurable: loopback, private (RFC 1918 / ULA) networks and an optional
host allowlist.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

from ..config import settings

_METADATA_HOSTS = {
    "metadata", "metadata.google.internal", "metadata.goog",
    "instance-data", "instance-data.ec2.internal",
}


class EgressError(ValueError):
    """Raised when a URL violates the outbound egress policy."""


def _allowlist() -> list[str]:
    return [h.strip().lower() for h in settings.egress_host_allowlist.split(",") if h.strip()]


def _host_allowed_by_list(host: str) -> bool:
    entries = _allowlist()
    if not entries:
        return True
    for entry in entries:
        if entry.startswith(".") and (host.endswith(entry) or host == entry[1:]):
            return True
        if host == entry:
            return True
    return False


def _check_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
        raise EgressError(f"Destination address {ip} is not permitted.")
    if ip.is_loopback and not settings.egress_allow_loopback:
        raise EgressError("Loopback destinations are disabled by egress policy.")
    if ip.is_private and not ip.is_loopback and not settings.egress_allow_private_networks:
        raise EgressError("Private-network destinations are disabled by egress policy.")


def validate_outbound_url(url: str | None, *, resolve: bool = True) -> str:
    """Return the normalised URL or raise :class:`EgressError`."""
    if not url:
        raise EgressError("URL is required.")
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https"):
        raise EgressError("Only http(s) URLs are allowed.")
    if parts.username or parts.password:
        raise EgressError("Credentials must not be embedded in URLs; use a secret reference.")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise EgressError("URL has no host.")
    if host in _METADATA_HOSTS:
        raise EgressError("Cloud metadata endpoints are not permitted.")
    if not _host_allowed_by_list(host):
        raise EgressError(f"Host '{host}' is not in the egress allowlist.")

    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        _check_ip(literal)
    elif host == "localhost" and not settings.egress_allow_loopback:
        raise EgressError("Loopback destinations are disabled by egress policy.")

    if resolve and literal is None:
        port = parts.port or (443 if parts.scheme == "https" else 80)
        try:
            infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
        except socket.gaierror as exc:
            raise EgressError(f"Could not resolve host '{host}'.") from exc
        for info in infos:
            _check_ip(ipaddress.ip_address(info[4][0]))
    return url.strip()
