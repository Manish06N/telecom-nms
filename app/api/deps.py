import uuid

from fastapi import Depends, Query
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.security import safe_decode
from app.db.session import get_db
from app.domain.enums import Permission
from app.domain.errors import AppError
from app.domain.permissions import role_has
from app.models.identity import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    """The token says who you claim to be. The user row says whether you still may."""
    try:
        payload = safe_decode(token)
    except ValueError as exc:
        raise AppError("Invalid or expired token", 401, "invalid_token") from exc
    if payload.get("type") != "access":
        raise AppError("Access token required", 401, "invalid_token")
    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise AppError("Invalid or expired token", 401, "invalid_token") from exc
    user = db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise AppError("Invalid or expired token", 401, "invalid_token")
    if not user.is_active:
        raise AppError("This account is deactivated", 403, "account_inactive")
    return user


def require(permission: Permission):
    def checker(user: User = Depends(get_current_user)) -> User:
        if not role_has(user.role, permission):
            raise AppError(f"Role '{user.role}' cannot perform this action", 403, "forbidden")
        return user

    return checker


class PageParams:
    def __init__(
        self,
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
        sort_by: str = Query("created_at"),
        sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
        q: str | None = Query(None, max_length=100),
    ):
        self.page = page
        self.page_size = page_size
        self.sort_by = sort_by
        self.sort_dir = sort_dir
        self.q = q


def as_page(rows, total: int, params: PageParams) -> dict:
    return {"items": rows, "total": total, "page": params.page, "page_size": params.page_size}
