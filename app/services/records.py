import logging
from enum import Enum

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.context import request_ip
from app.models.audit import AuditLog
from app.models.audit import AuditLog
from app.models.identity import User
from app.models.operations import Notification
from app.utils.time import utcnow

logger = logging.getLogger("telecom.notifications")


def log_action(
    db: Session,
    *,
    actor_id,
    action: str,
    entity: str,
    entity_id,
    previous: dict | None = None,
    new: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            user_id=actor_id,
            action=action,
            entity=entity,
            entity_id=str(entity_id),
            previous_value=previous,
            new_value=new,
            ip_address=request_ip.get(),
        )
    )
    db.flush()


def _text(value) -> str:
    if isinstance(value, Enum):
        return value.value
    return str(value)


def notify(db: Session, user_id, event_type: str, title: str, message: str, payload: dict | None = None):
    if user_id is None:
        return None
    row = Notification(
        user_id=user_id,
        event_type=_text(event_type),
        title=title,
        message=message,
        payload=payload,
    )
    db.add(row)
    db.flush()
    return row


def notify_roles(db: Session, roles: list[str], event_type: str, title: str, message: str, payload: dict | None = None):
    users = db.scalars(
        select(User).where(User.role.in_(roles), User.is_active.is_(True), User.deleted_at.is_(None))
    ).all()
    return [notify(db, user.id, event_type, title, message, payload) for user in users]


def deliver_pending() -> int:
    """Mark in-app notifications as handed to the delivery channel.

    The row is the record. This step is the 'send'. With DEBUG logging you can
    see it. Email is intentionally not required for the project to run.
    """
    if not settings.deliver_notifications:
        return 0
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        rows = list(db.scalars(select(Notification).where(Notification.delivered_at.is_(None))).all())
        now = utcnow()
        for row in rows:
            row.delivered_at = now
            logger.info("deliver %s to %s: %s", row.event_type, row.user_id, row.title)
        db.commit()
        return len(rows)
    except Exception:
        db.rollback()
        logger.exception("notification delivery failed")
        return 0
    finally:
        db.close()


def spawn(background_tasks) -> None:
    if background_tasks is not None:
        background_tasks.add_task(deliver_pending)


def list_logs(db: Session, params, *, entity, action, user_id, start, end, q):
    from app.repositories.common import apply_sort, paginate

    stmt = select(AuditLog)
    if entity:
        stmt = stmt.where(AuditLog.entity == entity)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if start:
        stmt = stmt.where(AuditLog.created_at >= start)
    if end:
        stmt = stmt.where(AuditLog.created_at < end)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where((AuditLog.action.ilike(like)) | (AuditLog.entity.ilike(like)))
    stmt = apply_sort(
        stmt,
        params.sort_by if params.sort_by in {"created_at", "action", "entity"} else "created_at",
        params.sort_dir,
        {"created_at": AuditLog.created_at, "action": AuditLog.action, "entity": AuditLog.entity},
    )
    return paginate(db, stmt, params.page, params.page_size)


def list_notifications(db: Session, user_id, unread_only: bool):
    from app.models.operations import Notification

    stmt = select(Notification).where(Notification.user_id == user_id).order_by(Notification.created_at.desc())
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    return list(db.scalars(stmt.limit(100)).all())


def mark_notification_read(db: Session, user_id, notification_id):
    from app.domain.errors import AppError
    from app.models.operations import Notification

    row = db.get(Notification, notification_id)
    if row is None or row.user_id != user_id:
        raise AppError("Notification not found", 404, "not_found")
    if row.read_at is None:
        row.read_at = utcnow()
    return row


def mark_all_notifications_read(db: Session, user_id) -> int:
    from app.models.operations import Notification

    rows = db.scalars(
        select(Notification).where(Notification.user_id == user_id, Notification.read_at.is_(None))
    ).all()
    now = utcnow()
    for row in rows:
        row.read_at = now
    return len(list(rows))

