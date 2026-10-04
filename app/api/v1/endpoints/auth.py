import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.api.deps import PageParams, as_page, get_current_user, require
from app.db.session import get_db
from app.domain.enums import Permission, Role
from app.schemas.contracts import (
    LoginRequest,
    LogoutRequest,
    Message,
    Page,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    ResetConfirm,
    ResetRequest,
    StaffCreate,
    TokenPair,
    UserRead,
)
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["Authentication"])
users = APIRouter(prefix="/users", tags=["Users"])


def _agent(request: Request) -> str | None:
    return request.headers.get("user-agent")


@router.post("/register", response_model=RegisterResponse, status_code=201)
def register(body: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    return auth_service.register_customer(db, body, _agent(request))


@router.post("/login", response_model=TokenPair)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    return auth_service.login(db, body.email, body.password, _agent(request))


@router.post("/token", response_model=TokenPair)
def token(request: Request, form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """Form login used by the Swagger Authorize button. The username is the email."""
    return auth_service.login(db, form.username, form.password, _agent(request))


@router.post("/refresh", response_model=TokenPair)
def refresh(body: RefreshRequest, request: Request, db: Session = Depends(get_db)):
    return auth_service.refresh(db, body.refresh_token, _agent(request))


@router.post("/logout", response_model=Message)
def logout(body: LogoutRequest, user=Depends(get_current_user), db: Session = Depends(get_db)):
    auth_service.logout(db, user, body.refresh_token)
    return {"message": "Logged out"}


@router.get("/me", response_model=UserRead)
def me(user=Depends(get_current_user)):
    return user


@router.post("/password-reset/request", response_model=Message)
def request_reset(body: ResetRequest, db: Session = Depends(get_db)):
    return auth_service.request_password_reset(db, body.email)


@router.post("/password-reset/confirm", response_model=Message)
def confirm_reset(body: ResetConfirm, db: Session = Depends(get_db)):
    return auth_service.confirm_password_reset(db, body.token, body.new_password)


@users.get("", response_model=Page[UserRead])
def list_users(
    params: PageParams = Depends(),
    role: Role | None = None,
    user=Depends(require(Permission.USER_MANAGE)),
    db: Session = Depends(get_db),
):
    rows, total = auth_service.list_users(db, page=params.page, page_size=params.page_size, q=params.q, role=role.value if role else None)
    return as_page(rows, total, params)


@users.post("", response_model=UserRead, status_code=201)
def create_staff(body: StaffCreate, user=Depends(require(Permission.USER_MANAGE)), db: Session = Depends(get_db)):
    return auth_service.create_staff(db, user, body)


@users.post("/{user_id}/activate", response_model=UserRead)
def activate(user_id: uuid.UUID, user=Depends(require(Permission.USER_MANAGE)), db: Session = Depends(get_db)):
    return auth_service.set_active(db, user, user_id, True)


@users.post("/{user_id}/deactivate", response_model=UserRead)
def deactivate(user_id: uuid.UUID, user=Depends(require(Permission.USER_MANAGE)), db: Session = Depends(get_db)):
    return auth_service.set_active(db, user, user_id, False)
