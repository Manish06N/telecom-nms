"""Query helpers shared by repositories."""

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.domain.errors import AppError
from app.models.identity import Sequence


def next_code(db: Session, series: str, prefix: str) -> str:
    stmt = select(Sequence).where(Sequence.name == series)
    if db.get_bind().dialect.name == "postgresql":
        stmt = stmt.with_for_update()
    row = db.scalar(stmt)
    if row is None:
        row = Sequence(name=series, value=0)
        db.add(row)
        db.flush()
    row.value += 1
    db.flush()
    return f"{prefix}-{row.value:06d}"


def apply_sort(stmt: Select, sort_by: str, sort_dir: str, allowed: dict):
    column = allowed.get(sort_by)
    if column is None:
        allowed_names = ", ".join(sorted(allowed))
        raise AppError(f"Cannot sort by '{sort_by}'. Allowed: {allowed_names}", 422, "invalid_sort")
    if sort_dir not in {"asc", "desc"}:
        raise AppError("sort_dir must be asc or desc", 422, "invalid_sort")
    return stmt.order_by(column.desc() if sort_dir == "desc" else column.asc())


def paginate(db: Session, stmt: Select, page: int, page_size: int):
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = list(db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).unique().all())
    return rows, total
