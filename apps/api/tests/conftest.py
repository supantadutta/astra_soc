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
