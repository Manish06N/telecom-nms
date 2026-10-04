import uuid
from datetime import date, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import PageParams, as_page, require
from app.db.session import get_db
from app.domain.enums import Permission
from app.schemas.contracts import AuditRead, NotificationRead, Page
from app.services import dashboard_service, operations_service
from app.services import records
from app.services import report_service

dashboard = APIRouter(prefix="/dashboard", tags=["Dashboard"])
reports = APIRouter(prefix="/reports", tags=["Reports"])
audit = APIRouter(prefix="/audit-logs", tags=["Audit logs"])
notifications = APIRouter(prefix="/notifications", tags=["Notifications"])
operations = APIRouter(prefix="/operations", tags=["Operations"])


def _export(rows: list[dict], export: str | None, filename: str):
    if export == "csv":
        return Response(
            report_service.rows_to_csv(rows),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}.csv"},
        )
    if export == "xlsx":
        return Response(
            report_service.rows_to_xlsx(rows),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}.xlsx"},
        )
    return None


def _window(date_from: date | None, date_to: date | None):
    return report_service.resolve_range(date_from, date_to)


@dashboard.get("/operations")
def operations_dashboard(user=Depends(require(Permission.DASHBOARD_READ)), db: Session = Depends(get_db)):
    return dashboard_service.operations_dashboard(db)


@reports.get("/customer-growth")
def customer_growth(
    params: PageParams = Depends(),
    date_from: date | None = None,
    date_to: date | None = None,
    city: str | None = None,
    export: str | None = Query(None, pattern="^(csv|xlsx)$"),
    user=Depends(require(Permission.REPORT_READ)),
    db: Session = Depends(get_db),
):
    start, end = _window(date_from, date_to)
    rows = report_service.customer_growth(db, start, end, city)
    exported = _export(rows, export, "customer-growth")
    return exported if exported is not None else report_service.page_rows(rows, params.page, params.page_size)


@reports.get("/subscription-trends")
def subscription_trends(
    params: PageParams = Depends(),
    date_from: date | None = None,
    date_to: date | None = None,
    plan_id: uuid.UUID | None = None,
    export: str | None = Query(None, pattern="^(csv|xlsx)$"),
    user=Depends(require(Permission.REPORT_READ)),
    db: Session = Depends(get_db),
):
    start, end = _window(date_from, date_to)
    rows = report_service.subscription_trends(db, start, end, plan_id)
    exported = _export(rows, export, "subscription-trends")
    return exported if exported is not None else report_service.page_rows(rows, params.page, params.page_size)


@reports.get("/plan-popularity")
def plan_popularity(
    params: PageParams = Depends(),
    date_from: date | None = None,
    date_to: date | None = None,
    plan_id: uuid.UUID | None = None,
    export: str | None = Query(None, pattern="^(csv|xlsx)$"),
    user=Depends(require(Permission.REPORT_READ)),
    db: Session = Depends(get_db),
):
    start, end = _window(date_from, date_to)
    rows = report_service.plan_popularity(db, start, end, plan_id)
    exported = _export(rows, export, "plan-popularity")
    return exported if exported is not None else report_service.page_rows(rows, params.page, params.page_size)


@reports.get("/data-consumption")
def data_consumption(
    params: PageParams = Depends(),
    date_from: date | None = None,
    date_to: date | None = None,
    customer_id: uuid.UUID | None = None,
    plan_id: uuid.UUID | None = None,
    city: str | None = None,
    export: str | None = Query(None, pattern="^(csv|xlsx)$"),
    user=Depends(require(Permission.REPORT_READ)),
    db: Session = Depends(get_db),
):
    start, end = _window(date_from, date_to)
    rows = report_service.data_consumption(db, start, end, customer_id, plan_id, city)
    exported = _export(rows, export, "data-consumption")
    return exported if exported is not None else report_service.page_rows(rows, params.page, params.page_size)


@reports.get("/network-uptime")
def network_uptime(
    params: PageParams = Depends(),
    date_from: date | None = None,
    date_to: date | None = None,
    city: str | None = None,
    export: str | None = Query(None, pattern="^(csv|xlsx)$"),
    user=Depends(require(Permission.REPORT_READ)),
    db: Session = Depends(get_db),
):
    start, end = _window(date_from, date_to)
    rows = report_service.network_uptime(db, start, end, city)
    exported = _export(rows, export, "network-uptime")
    return exported if exported is not None else report_service.page_rows(rows, params.page, params.page_size)


@reports.get("/outage-frequency")
def outage_frequency(
    params: PageParams = Depends(),
    date_from: date | None = None,
    date_to: date | None = None,
    city: str | None = None,
    export: str | None = Query(None, pattern="^(csv|xlsx)$"),
    user=Depends(require(Permission.REPORT_READ)),
    db: Session = Depends(get_db),
):
    start, end = _window(date_from, date_to)
    rows = report_service.outage_frequency(db, start, end, city)
    exported = _export(rows, export, "outage-frequency")
    return exported if exported is not None else report_service.page_rows(rows, params.page, params.page_size)


@reports.get("/ticket-resolution")
def ticket_resolution(
    date_from: date | None = None,
    date_to: date | None = None,
    status: str | None = None,
    customer_id: uuid.UUID | None = None,
    user=Depends(require(Permission.REPORT_READ)),
    db: Session = Depends(get_db),
):
    start, end = _window(date_from, date_to)
    return report_service.ticket_resolution(db, start, end, status, customer_id)


@reports.get("/sla-performance")
def sla_performance(
    date_from: date | None = None,
    date_to: date | None = None,
    customer_id: uuid.UUID | None = None,
    user=Depends(require(Permission.REPORT_READ)),
    db: Session = Depends(get_db),
):
    start, end = _window(date_from, date_to)
    return report_service.sla_performance(db, start, end, customer_id)


@reports.get("/technician-performance")
def technician_performance(
    params: PageParams = Depends(),
    date_from: date | None = None,
    date_to: date | None = None,
    export: str | None = Query(None, pattern="^(csv|xlsx)$"),
    user=Depends(require(Permission.REPORT_READ)),
    db: Session = Depends(get_db),
):
    start, end = _window(date_from, date_to)
    rows = report_service.technician_performance(db, start, end)
    exported = _export(rows, export, "technician-performance")
    return exported if exported is not None else report_service.page_rows(rows, params.page, params.page_size)


@reports.get("/service-trends")
def service_trends(
    date_from: date | None = None,
    date_to: date | None = None,
    customer_id: uuid.UUID | None = None,
    user=Depends(require(Permission.REPORT_READ)),
    db: Session = Depends(get_db),
):
    start, end = _window(date_from, date_to)
    return report_service.service_trends(db, start, end, customer_id)


@audit.get("", response_model=Page[AuditRead])
def list_audit(
    params: PageParams = Depends(),
    entity: str | None = None,
    action: str | None = None,
    user_id: uuid.UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    user=Depends(require(Permission.AUDIT_READ)),
    db: Session = Depends(get_db),
):
    rows, total = records.list_logs(
        db, params, entity=entity, action=action, user_id=user_id, start=date_from, end=date_to, q=params.q
    )
    return as_page(rows, total, params)


@notifications.get("", response_model=list[NotificationRead])
def list_notifications(unread_only: bool = False, user=Depends(require(Permission.NOTIFICATION_READ)), db: Session = Depends(get_db)):
    return records.list_notifications(db, user.id, unread_only)


@notifications.post("/{notification_id}/read", response_model=NotificationRead)
def mark_read(notification_id: uuid.UUID, user=Depends(require(Permission.NOTIFICATION_READ)), db: Session = Depends(get_db)):
    return records.mark_notification_read(db, user.id, notification_id)


@notifications.post("/read-all")
def mark_all(user=Depends(require(Permission.NOTIFICATION_READ)), db: Session = Depends(get_db)):
    count = records.mark_all_notifications_read(db, user.id)
    return {"updated": count}


@operations.post("/run-schedules")
def run_schedules(background: BackgroundTasks, user=Depends(require(Permission.SCHEDULE_RUN)), db: Session = Depends(get_db)):
    from app.core.config import settings

    if settings.task_backend == "celery":
        from app.workers.tasks import run_schedules_task_celery

        run_schedules_task_celery.delay()
        return {"queued": True}
    result = operations_service.run_schedules(db, background)
    return result
