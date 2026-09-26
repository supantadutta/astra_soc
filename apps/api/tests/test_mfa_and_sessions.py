"""MFA (TOTP + recovery codes), per-tenant MFA policy (including delegated
provider staff), admin reset, and browser cookie sessions with CSRF."""
from __future__ import annotations

import time
import uuid

import pytest
from conftest import as_tenant, login

PW = "Mfa!Account-Pass-1"


def _mk_user(client, headers, role, prefix="mfa") -> str:
    email = f"{prefix}-{uuid.uuid4().hex[:8]}@corp.local"
    r = client.post("/api/v1/rbac/users", headers=headers, json={
        "email": email, "full_name": "MFA Test", "password": PW, "roles": [role]})
    assert r.status_code == 200, r.text
    return email


def _bearer(r) -> dict:
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _enroll(client, headers) -> tuple[str, list[str]]:
    from astrasoc.auth.mfa import totp

    secret = client.post("/api/v1/auth/mfa/setup", headers=headers).json()["secret"]
    r = client.post("/api/v1/auth/mfa/enable", headers=headers, json={"code": totp(secret)})
    assert r.status_code == 200, r.text
    return secret, r.json()["recovery_codes"]


def _next_code(secret: str, steps: int = 1) -> str:
    from astrasoc.auth.mfa import totp

    return totp(secret, at=time.time() + 30 * steps)


# --- TOTP primitives ---------------------------------------------------------------
def test_totp_matches_rfc6238_vectors():
    from astrasoc.auth.mfa import totp

    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # base32("12345678901234567890")
    assert totp(secret, at=59, digits=8) == "94287082"
    assert totp(secret, at=1111111109, digits=8) == "07081804"
    assert totp(secret, at=1234567890, digits=8) == "89005924"


def test_totp_rejects_replay_and_far_drift():
    from astrasoc.auth.mfa import generate_secret, totp, verify_totp

    s = generate_secret()
    now = time.time()
    step = verify_totp(s, totp(s, at=now), None, at=now)
    assert step is not None
    assert verify_totp(s, totp(s, at=now), step, at=now) is None          # replay
    assert verify_totp(s, totp(s, at=now - 120), None, at=now) is None    # too old
    assert verify_totp(s, "12345", None, at=now) is None                  # malformed


def test_secret_is_encrypted_at_rest():
    from astrasoc.auth.mfa import decrypt_secret, encrypt_secret, generate_secret

    s = generate_secret()
    enc = encrypt_secret(s)
    assert s not in enc and decrypt_secret(enc) == s
    assert decrypt_secret(enc[:-4] + "AAAA") is None  # tampering detected


# --- Enrollment and two-step sign-in ----------------------------------------------------
def test_enroll_then_sign_in_requires_second_factor(client, admin):
    email = _mk_user(client, admin, "auditor")
    h = login(client, email, PW)                                  # no MFA yet: plain session
    secret, codes = _enroll(client, h)
    assert len(codes) == 10
    me = client.get("/api/v1/auth/me", headers=h).json()
    assert me["mfa_enabled"] and me["mfa_verified"]              # enrolling upgrades the session

    r = client.post("/api/v1/auth/login", json={"email": email, "password": PW})
    assert r.status_code == 200 and r.json()["mfa_required"] and "access_token" not in r.json()
    token = r.json()["mfa_token"]
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401

    bad = client.post("/api/v1/auth/login/mfa", json={"mfa_token": token, "code": "000000"})
    assert bad.status_code == 401
    ok = client.post("/api/v1/auth/login/mfa", json={"mfa_token": token, "code": _next_code(secret)})
    assert ok.status_code == 200, ok.text
    assert client.get("/api/v1/auth/me", headers=_bearer(ok)).json()["mfa_verified"] is True

    # A recovery code works exactly once.
    token2 = client.post("/api/v1/auth/login", json={"email": email, "password": PW}).json()["mfa_token"]
    rc = client.post("/api/v1/auth/login/mfa", json={"mfa_token": token2, "recovery_code": codes[0]})
    assert rc.status_code == 200 and rc.json()["recovery_codes_remaining"] == 9
    token3 = client.post("/api/v1/auth/login", json={"email": email, "password": PW}).json()["mfa_token"]
    assert client.post("/api/v1/auth/login/mfa",
                       json={"mfa_token": token3, "recovery_code": codes[0]}).status_code == 401


def test_mfa_challenge_failures_lock_the_account(client, admin):
    email = _mk_user(client, admin, "auditor")
    h = login(client, email, PW)
    secret, _ = _enroll(client, h)
    for _ in range(5):
        t = client.post("/api/v1/auth/login", json={"email": email, "password": PW}).json()["mfa_token"]
        client.post("/api/v1/auth/login/mfa", json={"mfa_token": t, "code": "000000"})
    # Locked: even the right password + code no longer works.
    r = client.post("/api/v1/auth/login", json={"email": email, "password": PW})
    assert r.status_code == 401


def test_mfa_material_is_never_serialized(client, admin):
    email = _mk_user(client, admin, "auditor")
    _enroll(client, login(client, email, PW))
    users = client.get("/api/v1/rbac/users", headers=admin).json()["items"]
    row = next(u for u in users if u["email"] == email)
    assert row["mfa_enabled"] is True
    for secret_field in ("mfa_secret_enc", "mfa_pending_secret_enc", "mfa_recovery_hashes", "password_hash"):
        assert secret_field not in row


def test_disable_requires_password_and_code(client, admin):
    email = _mk_user(client, admin, "auditor")
    h = login(client, email, PW)
    secret, _ = _enroll(client, h)
    assert client.post("/api/v1/auth/mfa/disable", headers=h,
                       json={"password": "wrong", "code": _next_code(secret)}).status_code == 400
    r = client.post("/api/v1/auth/mfa/disable", headers=h, json={"password": PW, "code": _next_code(secret, 1)})
    assert r.status_code == 200 and r.json()["enabled"] is False


# --- Tenant policy ------------------------------------------------------------------------
@pytest.fixture
def strict_customer(client, mssp_soc):
    """A freshly onboarded customer whose admin has enrolled MFA and then
    required it for the whole tenant."""
    slug = f"strict-{uuid.uuid4().hex[:6]}"
    admin_email = f"admin@{slug}.local"
    r = client.post("/api/v1/mssp/tenants", headers=mssp_soc, json={
        "name": f"Strict {slug}", "slug": slug, "service_tier": "enterprise", "status": "active",
        "admin": {"email": admin_email, "full_name": "Strict Admin", "password": PW}})
    assert r.status_code == 201, r.text
    ah = login(client, admin_email, PW)
    early_user = _mk_user(client, ah, "customer_viewer", prefix="early")
    early_session = login(client, early_user, PW)  # established before the policy

    # Requiring MFA without having it yourself is refused (would lock you out).
    r = client.patch("/api/v1/tenants/current", headers=ah, json={"security": {"require_mfa": True}})
    assert r.status_code == 409
    _enroll(client, ah)
    r = client.patch("/api/v1/tenants/current", headers=ah, json={"security": {"require_mfa": True}})
    assert r.status_code == 200, r.text
    return {"id": r.json()["id"], "slug": slug, "admin": ah, "early_session": early_session}


def test_tenant_policy_forces_enrollment_at_sign_in(client, strict_customer):
    from astrasoc.auth.mfa import totp

    email = _mk_user(client, strict_customer["admin"], "customer_viewer")
    r = client.post("/api/v1/auth/login", json={"email": email, "password": PW})
    assert r.json().get("mfa_enrollment_required") and "access_token" not in r.json()
    et = r.json()["enrollment_token"]
    secret = client.post("/api/v1/auth/mfa/setup", json={"enrollment_token": et}).json()["secret"]
    done = client.post("/api/v1/auth/mfa/enable", json={"enrollment_token": et, "code": totp(secret)})
    assert done.status_code == 200, done.text
    assert len(done.json()["recovery_codes"]) == 10
    me = client.get("/api/v1/auth/me", headers=_bearer(done)).json()
    assert me["mfa_verified"] and me["tenant_requires_mfa"]


def test_sessions_without_mfa_stop_working_when_policy_is_enabled(client, strict_customer):
    h = strict_customer["early_session"]
    r = client.get("/api/v1/incidents", headers=h)
    assert r.status_code == 403 and r.json()["error"] == "mfa_required"
    assert client.post("/api/v1/auth/logout", headers=h).status_code == 200  # can still sign out


def test_customer_mfa_policy_binds_delegated_provider_staff(client, strict_customer, mssp_soc, admin):
    # Provider staff without a second factor cannot enter.
    r = client.get("/api/v1/incidents", headers=as_tenant(mssp_soc, strict_customer["slug"]))
    assert r.status_code == 403 and r.json()["error"] == "mfa_required_by_tenant"
    # The same role with an MFA-verified session can.
    email = _mk_user(client, admin, "mssp_soc_manager", prefix="provider")
    ph = login(client, email, PW)
    _enroll(client, ph)
    assert client.get("/api/v1/incidents", headers=as_tenant(ph, strict_customer["slug"])).status_code == 200
    # The provider cannot lift a requirement the customer set.
    r = client.patch(f"/api/v1/mssp/tenants/{strict_customer['id']}", headers=ph, json={"require_mfa": False})
    assert r.status_code == 403
    # The switcher shows which tenants require MFA.
    listed = client.get("/api/v1/tenants", headers=ph).json()["items"]
    assert next(t for t in listed if t["slug"] == strict_customer["slug"])["requires_mfa"] is True


def test_mfa_cannot_be_disabled_where_required(client, strict_customer):
    r = client.post("/api/v1/auth/mfa/disable", headers=strict_customer["admin"],
                    json={"password": PW, "code": "123456"})
    assert r.status_code == 409 and r.json()["error"] == "tenant_requires_mfa"


def test_admin_can_reset_a_lost_authenticator(client, admin):
    email = _mk_user(client, admin, "auditor")
    h = login(client, email, PW)
    _enroll(client, h)
    uid = client.get("/api/v1/auth/me", headers=h).json()["id"]
    me_id = client.get("/api/v1/auth/me", headers=admin).json()["id"]
    assert client.post(f"/api/v1/rbac/users/{me_id}/mfa/reset", headers=admin).status_code == 400
    assert client.post(f"/api/v1/rbac/users/{uid}/mfa/reset", headers=admin).status_code == 200
    assert client.get("/api/v1/auth/me", headers=h).status_code == 401       # sessions revoked
    r = client.post("/api/v1/auth/login", json={"email": email, "password": PW})
    assert "access_token" in r.json()                                        # no second factor now


# --- Browser cookie sessions ----------------------------------------------------------------
@pytest.fixture
def browser(client):
    """A separate client (own cookie jar) so cookies never leak into other tests."""
    from fastapi.testclient import TestClient

    return TestClient(client.app)


def _cookies(r) -> dict[str, str]:
    out = {}
    for raw in r.headers.get_list("set-cookie"):
        name = raw.split("=", 1)[0]
        out[name] = raw.lower()
    return out


def test_cookie_session_keeps_tokens_away_from_javascript(browser):
    r = browser.post("/api/v1/auth/login", json={"email": "t1@acme.io", "password": "Demo!Pass123",
                                                 "session": "cookie"})
    assert r.status_code == 200 and "access_token" not in r.json() and "refresh_token" not in r.json()
    c = _cookies(r)
    assert "httponly" in c["astrasoc_at"] and "samesite=strict" in c["astrasoc_at"] and "path=/api" in c["astrasoc_at"]
    assert "httponly" in c["astrasoc_rt"] and "path=/api/v1/auth" in c["astrasoc_rt"]
    assert "httponly" not in c["astrasoc_csrf"]              # readable, for the double-submit header
    assert browser.get("/api/v1/auth/me").status_code == 200


def test_cookie_requests_that_change_state_need_the_csrf_token(browser):
    browser.post("/api/v1/auth/login", json={"email": "t1@acme.io", "password": "Demo!Pass123",
                                             "session": "cookie"})
    r = browser.post("/api/v1/stream/ticket")
    assert r.status_code == 403 and r.json()["error"] == "csrf_failed"
    r = browser.post("/api/v1/stream/ticket", headers={"X-CSRF-Token": "forged-value-forged-value"})
    assert r.status_code == 403
    csrf = browser.cookies.get("astrasoc_csrf")
    assert browser.post("/api/v1/stream/ticket", headers={"X-CSRF-Token": csrf}).status_code == 200


def test_cookie_refresh_rotates_and_logout_clears(browser):
    browser.post("/api/v1/auth/login", json={"email": "t1@acme.io", "password": "Demo!Pass123",
                                             "session": "cookie"})
    old_rt = browser.cookies.get("astrasoc_rt")
    csrf = browser.cookies.get("astrasoc_csrf")
    assert browser.post("/api/v1/auth/refresh").status_code == 403              # CSRF required
    r = browser.post("/api/v1/auth/refresh", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200 and "access_token" not in r.json()
    assert browser.cookies.get("astrasoc_rt") != old_rt
    csrf = browser.cookies.get("astrasoc_csrf")
    assert browser.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 200
    assert browser.get("/api/v1/auth/me").status_code == 401


def test_bearer_clients_are_unaffected_by_csrf(client):
    h = login(client, "t1@acme.io")
    assert client.post("/api/v1/stream/ticket", headers=h).status_code == 200


def test_cookie_session_via_mfa_step(browser, client, admin):
    email = _mk_user(client, admin, "auditor")
    secret, _ = _enroll(client, login(client, email, PW))
    t = browser.post("/api/v1/auth/login", json={"email": email, "password": PW, "session": "cookie"}).json()
    r = browser.post("/api/v1/auth/login/mfa", json={"mfa_token": t["mfa_token"], "code": _next_code(secret),
                                                     "session": "cookie"})
    assert r.status_code == 200 and "access_token" not in r.json()
    assert browser.get("/api/v1/auth/me").json()["mfa_verified"] is True


def test_production_guard_covers_session_and_encryption_settings():
    from astrasoc.config import Settings, production_problems

    base = dict(environment="production", jwt_secret="x" * 20 + "Qz9#" + "y" * 20,
                audit_key="a" * 20 + "Kp2!" + "b" * 20,
                database_url="postgresql+psycopg2://u@h/db", cors_origins="https://soc.example.com")
    assert production_problems(Settings(**base)) == []
    assert Settings(**base).secure_cookies is True
    assert production_problems(Settings(**base, data_encryption_key="")) == []          # unset in compose
    problems = " ".join(production_problems(Settings(**base, data_encryption_key="short",
                                                     cookie_secure=False)))
    assert "DATA_ENCRYPTION_KEY" in problems and "COOKIE_SECURE" in problems
