"""Authentication endpoints: login, refresh, logout, sessions, API keys, password."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import mfa
from ..auth.context import Principal
from ..auth.deps import get_current_principal, get_optional_principal
from ..auth.permissions import grant_violations
from ..auth.security import (
    create_access_token,
    create_refresh_token,
    generate_api_key,
    hash_password,
    hash_token,
    normalize_email,
    password_policy_errors,
    verify_password,
)
from ..auth.sessions import REFRESH_COOKIE, clear_session_cookies, csrf_ok, set_session_cookies
from ..config import settings
from ..db import get_db
from ..models import APIKey, Tenant, User
from ..models import Session as SessionModel
from ..schemas.auth import (
    APIKeyCreate,
    APIKeyCreated,
    LoginRequest,
    MeResponse,
    MFALoginRequest,
    RefreshRequest,
)
from ..services import audit
from ..services.mode import current_scope

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _invalid() -> HTTPException:
    # One uniform response for unknown user, wrong password and locked account
    # so the endpoint cannot be used to enumerate accounts.
    return HTTPException(status.HTTP_401_UNAUTHORIZED,
                         detail={"error": "invalid_credentials", "message": "Invalid credentials"})


def _client_ip(request: Request) -> str | None:
    return getattr(request.state, "client_ip", None) or (request.client.host if request.client else None)


def _create_session(db: Session, user: User, request: Request, *,
                    mfa_verified: bool) -> tuple[str, str]:
    sid = uuid.uuid4().hex
    access = create_access_token({"sub": str(user.id), "tid": str(user.tenant_id), "sid": sid})
    refresh, exp = create_refresh_token({"sub": str(user.id), "sid": sid})
    db.add(SessionModel(
        user_id=user.id, sid=sid, refresh_token_hash=hash_token(refresh),
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent", "")[:400], expires_at=exp,
        last_used_at=datetime.now(UTC), mfa_verified=mfa_verified,
    ))
    return access, refresh


def _session_response(access: str, refresh: str, delivery: str, extra: dict | None = None,
                      status_code: int = 200) -> JSONResponse:
    """``cookie``: HttpOnly cookies (browsers; tokens never reach page
    JavaScript). ``token``: tokens in the body (CLIs and integrations)."""
    body: dict = {"token_type": "cookie" if delivery == "cookie" else "bearer",
                  "expires_in": settings.access_token_ttl_seconds, **(extra or {})}
    if delivery != "cookie":
        body.update(access_token=access, refresh_token=refresh)
    response = JSONResponse(body, status_code=status_code)
    if delivery == "cookie":
        set_session_cookies(response, access, refresh)
    return response


def _complete_login(db: Session, user: User, request: Request, delivery: str, *,
                    method: str, extra: dict | None = None) -> JSONResponse:
    """Final step of every successful sign-in (password, MFA or enrollment)."""
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = datetime.now(UTC)
    access, refresh = _create_session(db, user, request, mfa_verified=method != "password")
    audit.record(db, action="auth.login", actor_id=user.id, actor_label=user.email,
                 tenant_id=user.tenant_id, data_scope=current_scope(db, user.tenant_id),
                 ip_address=_client_ip(request), detail={"method": method})
    db.commit()
    return _session_response(access, refresh, delivery, extra)


def _register_failure(db: Session, user: User, request: Request, *, stage: str) -> None:
    now = datetime.now(UTC)
    user.failed_login_count = (user.failed_login_count or 0) + 1
    if user.failed_login_count >= settings.login_max_failures:
        user.locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
        user.failed_login_count = 0
        audit.record(db, action="auth.account_locked", actor_id=user.id,
                     actor_label=user.email, tenant_id=user.tenant_id, outcome="failure",
                     data_scope=current_scope(db, user.tenant_id), ip_address=_client_ip(request),
                     detail={"minutes": settings.login_lockout_minutes, "stage": stage})


def _usable(db: Session, user: User | None) -> bool:
    if user is None or not user.is_active:
        return False
    tenant = db.get(Tenant, user.tenant_id)
    return tenant is not None and tenant.is_active


@router.get("/login-options")
def login_options() -> dict:
    """Unauthenticated: tells the sign-in page whether the well-known demo
    accounts exist, so production deployments never advertise them."""
    return {"demo_accounts": settings.should_seed_demo_users,
            "environment": "demo" if settings.should_seed_demo_users else "standard"}


@router.post("/login")
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    """Password step. Returns a session, or — when a second factor is needed —
    a short-lived challenge token for ``/auth/login/mfa`` (enrolled users) or
    ``/auth/mfa/setup`` + ``/auth/mfa/enable`` (tenant requires MFA, user not
    enrolled yet). A challenge token grants nothing else."""
    email = normalize_email(body.email)
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    now = datetime.now(UTC)
    ip = _client_ip(request)

    locked = bool(user and user.locked_until and user.locked_until > now)
    if user is None or locked or not verify_password(body.password, user.password_hash):
        if user is not None and not locked:
            _register_failure(db, user, request, stage="password")
        audit.record(
            db, action="auth.login_failed", actor_type="user", outcome="failure",
            tenant_id=user.tenant_id if user else None,
            data_scope=current_scope(db, user.tenant_id if user else None), ip_address=ip,
            detail={"email": email, "locked": locked, "stage": "password"},
        )
        db.commit()
        raise _invalid()
    if not _usable(db, user):
        raise _invalid()

    # The password is right, but the failure counter is only reset once the
    # whole sign-in (including any second factor) succeeds.
    if user.mfa_enabled:
        db.commit()
        return JSONResponse({"mfa_required": True, "mfa_token": mfa.issue_challenge(user.id, "mfa"),
                             "methods": ["totp", "recovery_code"]})
    tenant = db.get(Tenant, user.tenant_id)
    if mfa.tenant_requires_mfa(tenant) and not user.is_service_account:
        db.commit()
        return JSONResponse({"mfa_enrollment_required": True,
                             "enrollment_token": mfa.issue_challenge(user.id, "mfa_enroll")})
    return _complete_login(db, user, request, body.session, method="password")


@router.post("/login/mfa")
def login_mfa(body: MFALoginRequest, request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    """Second-factor step: a TOTP code or a single-use recovery code."""
    user_id = mfa.read_challenge(body.mfa_token, "mfa")
    user = db.get(User, user_id) if user_id else None
    now = datetime.now(UTC)
    if user is None or not user.mfa_enabled or not _usable(db, user) \
            or (user.locked_until and user.locked_until > now):
        raise _invalid()
    method, extra = None, {}
    if body.code:
        secret = mfa.decrypt_secret(user.mfa_secret_enc)
        step = mfa.verify_totp(secret, body.code, user.mfa_last_step) if secret else None
        if step is not None:
            user.mfa_last_step = step
            method = "totp"
    elif body.recovery_code:
        remaining = mfa.consume_recovery_code(body.recovery_code, list(user.mfa_recovery_hashes or []))
        if remaining is not None:
            user.mfa_recovery_hashes = remaining
            method = "recovery_code"
            extra = {"recovery_codes_remaining": len(remaining)}
    if method is None:
        _register_failure(db, user, request, stage="mfa")
        audit.record(db, action="auth.login_failed", actor_id=user.id, actor_label=user.email,
                     tenant_id=user.tenant_id, outcome="failure",
                     data_scope=current_scope(db, user.tenant_id), ip_address=_client_ip(request),
                     detail={"stage": "mfa"})
        db.commit()
        raise _invalid()
    return _complete_login(db, user, request, body.session, method=method, extra=extra)


# --- MFA management ----------------------------------------------------------------
def _mfa_subject(db: Session, principal: Principal | None, enrollment_token: str | None) -> User:
    if principal is not None and principal.session_id:
        user = db.get(User, principal.user_id)
    else:
        user_id = mfa.read_challenge(enrollment_token or "", "mfa_enroll")
        user = db.get(User, user_id) if user_id else None
    if user is None or not _usable(db, user):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail={
            "error": "unauthorized", "message": "Sign in (or use a valid enrollment token) first."})
    return user


@router.get("/mfa")
def mfa_status(principal: Principal = Depends(get_current_principal),
               db: Session = Depends(get_db)) -> dict:
    user = db.get(User, principal.user_id)
    home = db.get(Tenant, principal.home_tenant_id)
    return {"enabled": bool(user.mfa_enabled),
            "enrolled_at": user.mfa_enrolled_at.isoformat() if user.mfa_enrolled_at else None,
            "recovery_codes_remaining": len(user.mfa_recovery_hashes or []),
            "session_verified": principal.mfa_verified,
            "tenant_requires_mfa": mfa.tenant_requires_mfa(home)}


@router.post("/mfa/setup")
def mfa_setup(payload: dict = Body(default={}),
              principal: Principal | None = Depends(get_optional_principal),
              db: Session = Depends(get_db)) -> dict:
    """Start enrollment: returns a new secret and its otpauth:// URI (render as
    a QR code). Nothing changes until /mfa/enable confirms a code."""
    user = _mfa_subject(db, principal, payload.get("enrollment_token"))
    if user.mfa_enabled:
        raise HTTPException(409, detail={"error": "mfa_already_enabled",
                                         "message": "MFA is already enabled for this account."})
    secret = mfa.generate_secret()
    user.mfa_pending_secret_enc = mfa.encrypt_secret(secret)
    db.commit()
    return {"secret": secret, "otpauth_uri": mfa.provisioning_uri(secret, user.email, settings.mfa_issuer),
            "digits": mfa.DIGITS, "period": mfa.STEP_SECONDS}


@router.post("/mfa/enable")
def mfa_enable(request: Request, payload: dict = Body(...),
               principal: Principal | None = Depends(get_optional_principal),
               db: Session = Depends(get_db)) -> JSONResponse:
    """Confirm enrollment with a code from the authenticator. Returns the
    recovery codes (shown once). In the enrollment-token flow this also
    completes the sign-in."""
    enrollment_token = payload.get("enrollment_token")
    user = _mfa_subject(db, principal, enrollment_token)
    secret = mfa.decrypt_secret(user.mfa_pending_secret_enc)
    if user.mfa_enabled or not secret:
        raise HTTPException(409, detail={"error": "no_pending_enrollment",
                                         "message": "Start enrollment with /auth/mfa/setup first."})
    step = mfa.verify_totp(secret, str(payload.get("code", "")), None)
    if step is None:
        _register_failure(db, user, request, stage="mfa_enroll")
        db.commit()
        raise HTTPException(422, detail={"error": "invalid_code",
                                         "message": "That code is not valid. Check the device clock and try again."})
    codes = mfa.generate_recovery_codes()
    user.mfa_secret_enc, user.mfa_pending_secret_enc = user.mfa_pending_secret_enc, None
    user.mfa_enabled, user.mfa_last_step = True, step
    user.mfa_enrolled_at = datetime.now(UTC)
    user.mfa_recovery_hashes = [mfa.hash_recovery_code(c) for c in codes]
    audit.record(db, action="auth.mfa_enabled", actor_id=user.id, actor_label=user.email,
                 tenant_id=user.tenant_id, data_scope=current_scope(db, user.tenant_id),
                 ip_address=_client_ip(request))
    if principal is None or not principal.session_id:
        return _complete_login(db, user, request, str(payload.get("session", "token")),
                               method="totp_enrollment", extra={"recovery_codes": codes})
    # Enrolling proves possession of the new factor: upgrade this session.
    sess = db.execute(select(SessionModel).where(SessionModel.sid == principal.session_id)).scalar_one_or_none()
    if sess is not None:
        sess.mfa_verified = True
    db.commit()
    return JSONResponse({"enabled": True, "recovery_codes": codes})


def _verify_second_factor(user: User, payload: dict) -> bool:
    if payload.get("code"):
        secret = mfa.decrypt_secret(user.mfa_secret_enc)
        step = mfa.verify_totp(secret, str(payload["code"]), user.mfa_last_step) if secret else None
        if step is not None:
            user.mfa_last_step = step
            return True
        return False
    if payload.get("recovery_code"):
        remaining = mfa.consume_recovery_code(str(payload["recovery_code"]),
                                              list(user.mfa_recovery_hashes or []))
        if remaining is not None:
            user.mfa_recovery_hashes = remaining
            return True
    return False


@router.post("/mfa/disable")
def mfa_disable(request: Request, payload: dict = Body(...),
                principal: Principal = Depends(get_current_principal),
                db: Session = Depends(get_db)) -> dict:
    user = db.get(User, principal.user_id)
    if not user.mfa_enabled:
        raise HTTPException(409, detail={"error": "mfa_not_enabled", "message": "MFA is not enabled."})
    if mfa.tenant_requires_mfa(db.get(Tenant, user.tenant_id)):
        raise HTTPException(409, detail={"error": "tenant_requires_mfa",
                                         "message": "Your organization requires MFA; it cannot be turned off."})
    if not verify_password(str(payload.get("password", "")), user.password_hash) \
            or not _verify_second_factor(user, payload):
        _register_failure(db, user, request, stage="mfa_disable")
        db.commit()
        raise HTTPException(400, detail={"error": "verification_failed",
                                         "message": "Password or code is incorrect."})
    user.mfa_enabled, user.mfa_secret_enc, user.mfa_pending_secret_enc = False, None, None
    user.mfa_recovery_hashes, user.mfa_last_step, user.mfa_enrolled_at = [], None, None
    audit.record(db, action="auth.mfa_disabled", actor_id=user.id, actor_label=user.email,
                 tenant_id=user.tenant_id, data_scope=current_scope(db, user.tenant_id),
                 ip_address=_client_ip(request))
    db.commit()
    return {"enabled": False}


@router.post("/mfa/recovery-codes")
def mfa_regenerate_recovery(request: Request, payload: dict = Body(...),
                            principal: Principal = Depends(get_current_principal),
                            db: Session = Depends(get_db)) -> dict:
    """Replace all recovery codes (requires a current TOTP code)."""
    user = db.get(User, principal.user_id)
    if not user.mfa_enabled or not payload.get("code") or not _verify_second_factor(user, {"code": payload["code"]}):
        _register_failure(db, user, request, stage="mfa_recovery")
        db.commit()
        raise HTTPException(400, detail={"error": "verification_failed", "message": "Code is incorrect."})
    codes = mfa.generate_recovery_codes()
    user.mfa_recovery_hashes = [mfa.hash_recovery_code(c) for c in codes]
    audit.record(db, action="auth.mfa_recovery_codes_regenerated", actor_id=user.id,
                 actor_label=user.email, tenant_id=user.tenant_id,
                 data_scope=current_scope(db, user.tenant_id), ip_address=_client_ip(request))
    db.commit()
    return {"recovery_codes": codes}


@router.post("/refresh")
def refresh(request: Request, body: RefreshRequest | None = None,
            db: Session = Depends(get_db)) -> JSONResponse:
    """Rotate the refresh token (from the body, or the session cookie for
    browsers). Presenting an already-rotated token is treated as token theft:
    the whole session is revoked. The one exception is the token superseded
    by the latest rotation, within `refresh_reuse_grace_seconds`: a browser
    that navigates mid-refresh never receives the rotated cookie and
    legitimately presents the previous one again."""
    delivery = "token"
    token = body.refresh_token if body and body.refresh_token else None
    if token is None:
        token = request.cookies.get(REFRESH_COOKIE)
        delivery = "cookie"
        if token and not csrf_ok(request):
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail={
                "error": "csrf_failed", "message": "Missing or invalid CSRF token."})
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="No refresh token")
    token_hash = hash_token(token)
    now = datetime.now(UTC)
    sess = db.execute(select(SessionModel).where(
        SessionModel.refresh_token_hash == token_hash)).scalar_one_or_none()
    if sess is None:
        reused = db.execute(select(SessionModel).where(
            SessionModel.previous_token_hash == token_hash)).scalar_one_or_none()
        grace = settings.refresh_reuse_grace_seconds
        if (reused is not None and reused.revoked_at is None and grace > 0
                and reused.last_used_at is not None
                and now - reused.last_used_at <= timedelta(seconds=grace)):
            # Rotating again moves this token out of `previous`, so it is
            # accepted at most once.
            sess = reused
        else:
            if reused is not None and reused.revoked_at is None:
                reused.revoked_at = now
                reused.revoked_reason = "refresh_token_reuse"
                audit.record(db, action="auth.refresh_reuse_detected", actor_id=reused.user_id,
                             outcome="failure", ip_address=_client_ip(request),
                             detail={"session": str(reused.id)})
                db.commit()
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")
    if sess.revoked_at is not None or sess.expires_at < now:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")
    user = db.get(User, sess.user_id)
    if not _usable(db, user):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="User or tenant inactive")

    new_refresh, _ = create_refresh_token({"sub": str(user.id), "sid": sess.sid})
    sess.previous_token_hash = sess.refresh_token_hash
    sess.refresh_token_hash = hash_token(new_refresh)
    sess.last_used_at = now
    access = create_access_token({"sub": str(user.id), "tid": str(user.tenant_id), "sid": sess.sid})
    db.commit()
    return _session_response(access, new_refresh, delivery)


@router.post("/logout")
def logout(
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Revoke the caller's session server-side. Every access and refresh token
    issued for it stops working immediately."""
    if principal.session_id:
        sess = db.execute(select(SessionModel).where(
            SessionModel.sid == principal.session_id)).scalar_one_or_none()
        if sess and sess.revoked_at is None:
            sess.revoked_at = datetime.now(UTC)
            sess.revoked_reason = "logout"
    audit.record(db, action="auth.logout", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, actor_label=principal.email)
    db.commit()
    response = JSONResponse({"status": "logged_out"})
    clear_session_cookies(response)
    return response


@router.get("/me", response_model=MeResponse)
def me(principal: Principal = Depends(get_current_principal),
       db: Session = Depends(get_db)) -> MeResponse:
    tenant = db.get(Tenant, principal.tenant_id)
    user = db.get(User, principal.user_id)
    home_id = principal.home_tenant_id or principal.tenant_id
    return MeResponse(
        id=str(principal.user_id),
        email=principal.email,
        full_name=principal.full_name,
        tenant_id=str(principal.tenant_id),
        roles=principal.roles,
        permissions=principal.permissions,
        is_service_account=principal.is_service_account,
        tenant_slug=tenant.slug if tenant else principal.tenant_slug,
        tenant_name=tenant.name if tenant else "",
        tenant_kind=tenant.kind if tenant else "",
        home_tenant_id=str(home_id),
        home_tenant_slug=principal.home_tenant_slug or (tenant.slug if tenant else ""),
        home_permissions=principal.home_permissions or principal.permissions,
        delegated_via=principal.delegated_via,
        mfa_enabled=bool(user.mfa_enabled) if user else False,
        mfa_verified=principal.mfa_verified,
        tenant_requires_mfa=mfa.tenant_requires_mfa(tenant),
    )


@router.get("/sessions")
def list_sessions(
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict:
    rows = db.execute(
        select(SessionModel).where(SessionModel.user_id == principal.user_id)
        .order_by(SessionModel.created_at.desc()).limit(50)
    ).scalars().all()
    return {"items": [{
        "id": str(s.id), "ip_address": s.ip_address, "user_agent": s.user_agent,
        "created_at": s.created_at.isoformat(), "expires_at": s.expires_at.isoformat(),
        "last_used_at": s.last_used_at.isoformat() if s.last_used_at else None,
        "revoked": s.revoked_at is not None, "revoked_reason": s.revoked_reason,
        "current": s.sid == principal.session_id,
    } for s in rows]}


@router.post("/sessions/{session_id}/revoke")
def revoke_session(session_id: uuid.UUID,
                   principal: Principal = Depends(get_current_principal),
                   db: Session = Depends(get_db)) -> dict:
    sess = db.get(SessionModel, session_id)
    if sess is None or sess.user_id != principal.user_id:
        raise HTTPException(404, detail="Session not found")
    if sess.revoked_at is None:
        sess.revoked_at = datetime.now(UTC)
        sess.revoked_reason = "user_revoked"
    audit.record(db, action="auth.session_revoked", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, resource_type="session", resource_id=str(session_id))
    db.commit()
    return {"status": "revoked"}


@router.post("/password")
def change_password(payload: dict = Body(...),
                    principal: Principal = Depends(get_current_principal),
                    db: Session = Depends(get_db)) -> dict:
    """Change own password. Revokes every other session of the user."""
    user = db.get(User, principal.user_id)
    if user is None or not verify_password(str(payload.get("current_password", "")), user.password_hash):
        raise HTTPException(400, detail={"error": "invalid_password",
                                         "message": "Current password is incorrect."})
    new = str(payload.get("new_password", ""))
    problems = password_policy_errors(new)
    if problems:
        raise HTTPException(422, detail={"error": "weak_password", "message": "; ".join(problems)})
    user.password_hash = hash_password(new)
    user.password_changed_at = datetime.now(UTC)
    for s in db.execute(select(SessionModel).where(
            SessionModel.user_id == user.id, SessionModel.revoked_at.is_(None))).scalars():
        if s.sid != principal.session_id:
            s.revoked_at = datetime.now(UTC)
            s.revoked_reason = "password_changed"
    audit.record(db, action="auth.password_changed", actor_id=user.id,
                 tenant_id=user.tenant_id, actor_label=user.email)
    db.commit()
    return {"status": "password_changed"}


# --- API keys ----------------------------------------------------------------
@router.get("/api-keys")
def list_api_keys(principal: Principal = Depends(get_current_principal),
                  db: Session = Depends(get_db)) -> dict:
    principal.require("user:manage")
    rows = db.execute(select(APIKey).where(APIKey.tenant_id == principal.tenant_id)
                      .order_by(APIKey.created_at.desc())).scalars().all()
    return {"items": [{
        "id": str(k.id), "name": k.name, "prefix": k.prefix, "scopes": k.scopes,
        "expires_at": k.expires_at.isoformat() if k.expires_at else None,
        "revoked": k.revoked_at is not None,
        "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
    } for k in rows]}


@router.post("/api-keys", response_model=APIKeyCreated, status_code=201)
def create_api_key(
    body: APIKeyCreate,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> APIKeyCreated:
    principal.require("user:manage")
    if not body.scopes:
        raise HTTPException(422, detail={"error": "scopes_required",
                                         "message": "API keys must declare explicit scopes."})
    bad = grant_violations(principal.permissions, body.scopes)
    if bad:
        raise HTTPException(403, detail={"error": "scope_not_grantable",
                                         "message": "You cannot grant scopes you do not hold.",
                                         "detail": bad})
    days = body.expires_in_days or 90
    if days < 1 or days > 365:
        raise HTTPException(422, detail="expires_in_days must be between 1 and 365")
    full, prefix, key_hash = generate_api_key()
    key = APIKey(
        tenant_id=principal.tenant_id, user_id=principal.user_id, name=body.name,
        prefix=prefix, key_hash=key_hash, scopes=body.scopes,
        expires_at=datetime.now(UTC) + timedelta(days=days),
    )
    db.add(key)
    db.flush()
    audit.record(db, action="apikey.created", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, resource_type="api_key", resource_id=str(key.id),
                 detail={"name": body.name, "scopes": body.scopes, "expires_in_days": days})
    db.commit()
    return APIKeyCreated(
        id=str(key.id), name=key.name, prefix=prefix, api_key=full, scopes=body.scopes
    )


@router.post("/api-keys/{key_id}/revoke")
def revoke_api_key(key_id: uuid.UUID,
                   principal: Principal = Depends(get_current_principal),
                   db: Session = Depends(get_db)) -> dict:
    principal.require("user:manage")
    key = db.get(APIKey, key_id)
    if key is None or key.tenant_id != principal.tenant_id:
        raise HTTPException(404, detail="API key not found")
    key.revoked_at = key.revoked_at or datetime.now(UTC)
    audit.record(db, action="apikey.revoked", actor_id=principal.user_id,
                 tenant_id=principal.tenant_id, resource_type="api_key", resource_id=str(key_id))
    db.commit()
    return {"status": "revoked"}
