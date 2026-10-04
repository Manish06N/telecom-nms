"""Login sessions.

Access tokens are short and are not stored. Refresh tokens are stored as a hash.
Presenting a rotated refresh token again revokes every session for that user.
"""

import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    hash_token,
    safe_decode,
    verify_password,
)
from app.domain.enums import Role
from app.domain.errors import AppError
from app.models.identity import PasswordResetToken, RefreshToken, User
from app.services.records import log_action
from app.utils.serialize import snapshot
from app.utils.time import utcnow

USER_FIELDS = ("email", "full_name", "role", "is_active")


def _tokens(db: Session, user: User, user_agent: str | None) -> dict:
    access = create_access_token(user.id)
    refresh, expires_at = create_refresh_token(user.id)
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_token(refresh),
            expires_at=expires_at,
            user_agent=user_agent,
        )
    )
    db.flush()
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in": settings.access_token_expire_minutes * 60,
    }


def _revoke_all(db: Session, user_id, reason: str) -> None:
    rows = db.scalars(
        select(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
    ).all()
    now = utcnow()
    for row in rows:
        row.revoked_at = now
        row.revoke_reason = reason


def _find_refresh(db: Session, raw_token: str) -> RefreshToken:
    try:
        payload = safe_decode(raw_token)
    except ValueError as exc:
        raise AppError("Refresh token is invalid", 401, "invalid_token") from exc
    if payload.get("type") != "refresh":
        raise AppError("Refresh token is invalid", 401, "invalid_token")
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw_token)))
    if row is None:
        raise AppError("Refresh token is not recognized", 401, "invalid_token")
    return row


def register_customer(db: Session, data, user_agent: str | None = None) -> dict:
    email = data.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise AppError("An account with this email already exists", 409, "email_taken")
    user = User(
        email=email,
        full_name=data.full_name.strip(),
        phone=data.phone,
        hashed_password=hash_password(data.password),
        role=Role.CUSTOMER.value,
        is_active=True,
        is_verified=True,
    )
    db.add(user)
    db.flush()
    log_action(db, actor_id=user.id, action="auth.register", entity="user", entity_id=user.id, new=snapshot(user, USER_FIELDS))
    return {"user": user, "tokens": _tokens(db, user, user_agent)}


def create_staff(db: Session, actor: User, data) -> User:
    if Role(data.role) == Role.CUSTOMER:
        raise AppError("Create customers from the customer API", 400, "use_customer_api")
    email = data.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise AppError("An account with this email already exists", 409, "email_taken")
    user = User(
        email=email,
        full_name=data.full_name.strip(),
        phone=data.phone,
        hashed_password=hash_password(data.password),
        role=Role(data.role).value,
        is_active=True,
        is_verified=True,
    )
    db.add(user)
    db.flush()
    log_action(
        db,
        actor_id=actor.id,
        action="user.created",
        entity="user",
        entity_id=user.id,
        new=snapshot(user, USER_FIELDS),
    )
    return user


def login(db: Session, email: str, password: str, user_agent: str | None = None) -> dict:
    user = db.scalar(select(User).where(User.email == email.lower(), User.deleted_at.is_(None)))
    if user is None or not verify_password(password, user.hashed_password):
        raise AppError("Incorrect email or password", 401, "invalid_credentials")
    if not user.is_active:
        raise AppError("This account is deactivated", 403, "account_inactive")
    user.last_login_at = utcnow()
    log_action(
        db,
        actor_id=user.id,
        action="auth.login",
        entity="user",
        entity_id=user.id,
        new={"email": user.email, "role": user.role},
    )
    return _tokens(db, user, user_agent)


def refresh(db: Session, raw_token: str, user_agent: str | None = None) -> dict:
    row = _find_refresh(db, raw_token)
    if row.revoked_at is not None:
        if row.revoke_reason == "rotation":
            _revoke_all(db, row.user_id, "reuse")
            log_action(
                db,
                actor_id=row.user_id,
                action="auth.refresh_reuse",
                entity="user",
                entity_id=row.user_id,
                new={"detail": "rotated refresh token was presented again"},
            )
            # A failed request normally rolls back. This lockout has to stick,
            # otherwise the stolen newer token would still work.
            db.commit()
            raise AppError("Refresh token reuse detected. All sessions were revoked.", 401, "token_reuse")
        raise AppError("Refresh token is no longer valid", 401, "invalid_token")
    if row.expires_at < utcnow():
        raise AppError("Refresh token has expired", 401, "invalid_token")
    user = db.get(User, row.user_id)
    if user is None or user.deleted_at is not None or not user.is_active:
        raise AppError("This account is deactivated", 403, "account_inactive")
    row.revoked_at = utcnow()
    row.revoke_reason = "rotation"
    return _tokens(db, user, user_agent)


def logout(db: Session, user: User, raw_token: str) -> None:
    row = _find_refresh(db, raw_token)
    if row.user_id != user.id:
        raise AppError("Refresh token is not recognized", 401, "invalid_token")
    if row.revoked_at is None:
        row.revoked_at = utcnow()
        row.revoke_reason = "logout"
    log_action(db, actor_id=user.id, action="auth.logout", entity="user", entity_id=user.id, new={"email": user.email})


def request_password_reset(db: Session, email: str) -> dict:
    user = db.scalar(select(User).where(User.email == email.lower(), User.deleted_at.is_(None)))
    raw = None
    if user is not None and user.is_active:
        raw = secrets.token_urlsafe(32)
        db.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=hash_token(raw),
                expires_at=utcnow() + timedelta(minutes=settings.password_reset_minutes),
            )
        )
        log_action(db, actor_id=user.id, action="auth.password_reset_requested", entity="user", entity_id=user.id)
    # Same response whether or not the email exists.
    body = {"message": "If that account exists, a reset token has been created."}
    if settings.debug and raw is not None:
        body["reset_token"] = raw
    return body


def confirm_password_reset(db: Session, raw_token: str, new_password: str) -> dict:
    row = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_token(raw_token)))
    if row is None or row.used_at is not None or row.expires_at < utcnow():
        raise AppError("Reset token is invalid or expired", 400, "invalid_reset_token")
    user = db.get(User, row.user_id)
    if user is None or user.deleted_at is not None:
        raise AppError("Reset token is invalid or expired", 400, "invalid_reset_token")
    user.hashed_password = hash_password(new_password)
    row.used_at = utcnow()
    _revoke_all(db, user.id, "password_reset")
    log_action(db, actor_id=user.id, action="auth.password_reset", entity="user", entity_id=user.id)
    return {"message": "Password updated. Sign in with the new password."}


def set_active(db: Session, actor: User, user_id, active: bool) -> User:
    if actor.id == user_id and not active:
        raise AppError("You cannot deactivate your own account", 400, "self_deactivate")
    user = db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise AppError("User not found", 404, "not_found")
    previous = snapshot(user, ("is_active",))
    user.is_active = active
    if not active:
        _revoke_all(db, user.id, "deactivated")
    log_action(
        db,
        actor_id=actor.id,
        action="user.activated" if active else "user.deactivated",
        entity="user",
        entity_id=user.id,
        previous=previous,
        new=snapshot(user, ("is_active",)),
    )
    return user


def list_users(db: Session, *, page: int, page_size: int, q: str | None, role: str | None):
    from app.repositories.common import apply_sort, paginate

    stmt = select(User).where(User.deleted_at.is_(None))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where((User.email.ilike(like)) | (User.full_name.ilike(like)))
    if role:
        stmt = stmt.where(User.role == role)
    stmt = apply_sort(stmt, "created_at", "desc", {"created_at": User.created_at, "email": User.email})
    return paginate(db, stmt, page, page_size)
