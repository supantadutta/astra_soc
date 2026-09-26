"""Pytest fixtures: an isolated app + client backed by a temp SQLite DB."""
from __future__ import annotations

import os
import tempfile

import pytest

# Configure a throwaway DB and test mode BEFORE importing the app/settings.
_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["ASTRASOC_ENVIRONMENT"] = "test"
os.environ["ASTRASOC_DATABASE_URL"] = f"sqlite:///{_TMP.name}"
os.environ["ASTRASOC_DEMO_SEED_ON_STARTUP"] = "true"
os.environ["ASTRASOC_JWT_SECRET"] = "test-secret-please-change-to-a-long-value-32b+"


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from astrasoc.main import app

    with TestClient(app) as c:
        yield c


def _login(client, email: str, password: str = "Demo!Pass123") -> dict:
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def manager(client):
    return _login(client, "manager@acme.io")


@pytest.fixture
def commander(client):
    return _login(client, "commander@acme.io")


@pytest.fixture
def tier1(client):
    return _login(client, "t1@acme.io")


@pytest.fixture
def auditor(client):
    return _login(client, "auditor@acme.io")


@pytest.fixture
def admin(client):
    return _login(client, "admin@astrasoc.io")


def login(client, email: str, password: str = "Demo!Pass123") -> dict:
    return _login(client, email, password)


@pytest.fixture
def t2(client):
    return _login(client, "t2@acme.io")


@pytest.fixture
def t3(client):
    return _login(client, "t3@acme.io")


# --- MSSP personas --------------------------------------------------------
@pytest.fixture
def mssp_soc(client):
    """Provider SOC manager: delegated access to every customer."""
    return _login(client, "soc@astrasoc.io")


@pytest.fixture
def mssp_analyst(client):
    """Provider analyst: only customers explicitly granted (acme, globex)."""
    return _login(client, "analyst@astrasoc.io")


@pytest.fixture
def mssp_accounts(client):
    return _login(client, "accounts@astrasoc.io")


@pytest.fixture
def acme_ciso(client):
    return _login(client, "ciso@acme.io")


@pytest.fixture
def globex_admin(client):
    return _login(client, "admin@globex.io")


def as_tenant(headers: dict, tenant: str) -> dict:
    return {**headers, "X-Tenant-ID": tenant}
