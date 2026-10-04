"""Towers, equipment, and outages. Affected customers are snapshotted when the outage opens."""

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.domain.enums import (
    CustomerStatus,
    NotificationEvent,
    OutageStatus,
    Role,
    Severity,
    TowerStatus,
)
from app.domain.errors import AppError
from app.domain.transitions import OUTAGE_TRANSITIONS, assert_transition
from app.models.customer import Customer, CustomerTower
from app.models.identity import User
from app.models.network import Equipment, Outage, OutageCustomer, Tower, outage_towers
from app.repositories.common import apply_sort, next_code, paginate
from app.services.access import is_customer, linked_customer
from app.services.records import log_action, notify, notify_roles, spawn
from app.utils.serialize import snapshot
from app.utils.time import utcnow

TOWER_FIELDS = ("name", "tower_type", "city", "status", "capacity", "coverage_radius_km")


def _tower(db: Session, tower_id) -> Tower:
    tower = db.get(Tower, tower_id)
    if tower is None or tower.deleted_at is not None:
        raise AppError("Tower not found", 404, "not_found")
    return tower


def create_tower(db: Session, actor: User, data) -> Tower:
    tower = Tower(
        tower_code=next_code(db, "tower", "TWR"),
        name=data.name.strip(),
        tower_type=data.tower_type.value,
        latitude=data.latitude,
        longitude=data.longitude,
        address=data.address.strip(),
        city=data.city.strip(),
        state=data.state.strip(),
        coverage_radius_km=data.coverage_radius_km,
        capacity=data.capacity,
        status=TowerStatus.ACTIVE.value,
    )
    db.add(tower)
    db.flush()
    log_action(db, actor_id=actor.id, action="tower.created", entity="tower", entity_id=tower.id, new=snapshot(tower, TOWER_FIELDS))
    return tower


def update_tower(db: Session, actor: User, tower_id, data) -> Tower:
    tower = _tower(db, tower_id)
    if tower.status == TowerStatus.DECOMMISSIONED.value:
        raise AppError("A decommissioned tower cannot be edited", 409, "tower_decommissioned")
    previous = snapshot(tower, TOWER_FIELDS)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(tower, field, value.value if hasattr(value, "value") else value)
    if tower.capacity < _mapped_customers(db, tower.id):
        raise AppError("Capacity cannot be lower than the customers already mapped", 409, "tower_full")
    log_action(
        db,
        actor_id=actor.id,
        action="tower.updated",
        entity="tower",
        entity_id=tower.id,
        previous=previous,
        new=snapshot(tower, TOWER_FIELDS),
    )
    return tower


def set_tower_status(db: Session, actor: User, tower_id, status: TowerStatus) -> Tower:
    tower = _tower(db, tower_id)
    if tower.status == TowerStatus.DECOMMISSIONED.value:
        raise AppError("A decommissioned tower stays decommissioned", 409, "tower_decommissioned")
    if status == TowerStatus.DECOMMISSIONED and _mapped_customers(db, tower.id):
        raise AppError("Unmap customers before decommissioning this tower", 409, "tower_in_use")
    previous = snapshot(tower, ("status",))
    tower.status = status.value
    log_action(
        db,
        actor_id=actor.id,
        action="tower.status_changed",
        entity="tower",
        entity_id=tower.id,
        previous=previous,
        new=snapshot(tower, ("status",)),
    )
    return tower


def _mapped_customers(db: Session, tower_id) -> int:
    return db.scalar(select(func.count()).select_from(CustomerTower).where(CustomerTower.tower_id == tower_id)) or 0


def map_customer_tower(db: Session, actor: User, customer_id, tower_id, is_primary: bool) -> CustomerTower:
    from app.services.customer_service import get_customer

    customer = get_customer(db, actor, customer_id)
    tower = _tower(db, tower_id)
    if tower.status != TowerStatus.ACTIVE.value:
        raise AppError("Customers can be mapped only to an active tower", 409, "tower_unavailable")
    existing = db.scalar(
        select(CustomerTower).where(CustomerTower.customer_id == customer.id, CustomerTower.tower_id == tower.id)
    )
    if existing:
        raise AppError("This customer is already mapped to that tower", 409, "already_mapped")
    if _mapped_customers(db, tower.id) >= tower.capacity:
        raise AppError("This tower is at capacity", 409, "tower_full")
    if is_primary:
        current = db.scalars(select(CustomerTower).where(CustomerTower.customer_id == customer.id)).all()
        for row in current:
            row.is_primary = False
    link = CustomerTower(customer_id=customer.id, tower_id=tower.id, is_primary=is_primary)
    db.add(link)
    db.flush()
    log_action(
        db,
        actor_id=actor.id,
        action="customer.tower_mapped",
        entity="customer",
        entity_id=customer.id,
        new={"tower_id": str(tower.id), "tower_code": tower.tower_code},
    )
    return link


def list_towers(db: Session, params, *, status, city, tower_type):
    stmt = select(Tower).where(Tower.deleted_at.is_(None))
    if status:
        stmt = stmt.where(Tower.status == status)
    if city:
        stmt = stmt.where(Tower.city.ilike(city.strip()))
    if tower_type:
        stmt = stmt.where(Tower.tower_type == tower_type)
    if params.q:
        like = f"%{params.q.strip()}%"
        stmt = stmt.where((Tower.name.ilike(like)) | (Tower.tower_code.ilike(like)) | (Tower.city.ilike(like)))
    stmt = apply_sort(
        stmt,
        params.sort_by,
        params.sort_dir,
        {"created_at": Tower.created_at, "name": Tower.name, "city": Tower.city, "tower_code": Tower.tower_code},
    )
    return paginate(db, stmt, params.page, params.page_size)


def register_equipment(db: Session, actor: User, data) -> Equipment:
    tower = _tower(db, data.tower_id)
    if db.scalar(select(Equipment).where(Equipment.serial_number == data.serial_number.strip())):
        raise AppError("This serial number is already registered", 409, "duplicate_serial")
    item = Equipment(
        tower_id=tower.id,
        equipment_type=data.equipment_type.value,
        serial_number=data.serial_number.strip(),
        model=data.model.strip(),
        manufacturer=data.manufacturer.strip(),
        health=data.health.value,
        installation_date=data.installation_date,
        next_maintenance_date=data.next_maintenance_date,
        network_status="up",
    )
    db.add(item)
    db.flush()
    _maintenance_notice(db, item)
    log_action(
        db,
        actor_id=actor.id,
        action="equipment.registered",
        entity="equipment",
        entity_id=item.id,
        new={"serial_number": item.serial_number, "tower_id": str(tower.id)},
    )
    return item


def heartbeat(db: Session, actor: User, equipment_id, data) -> Equipment:
    item = db.get(Equipment, equipment_id)
    if item is None:
        raise AppError("Equipment not found", 404, "not_found")
    now = utcnow()
    if item.network_status != "down" and data.network_status.value == "down":
        item.down_since = now
    if item.network_status == "down" and data.network_status.value != "down" and item.down_since is not None:
        item.downtime_minutes += max(0, int((now - item.down_since).total_seconds() // 60))
        item.down_since = None
    item.cpu_usage = data.cpu_usage
    item.memory_usage = data.memory_usage
    item.network_status = data.network_status.value
    item.health = data.health.value if data.health else item.health
    item.last_heartbeat = now
    log_action(
        db,
        actor_id=actor.id,
        action="equipment.heartbeat",
        entity="equipment",
        entity_id=item.id,
        new={"network_status": item.network_status, "cpu_usage": str(item.cpu_usage), "memory_usage": str(item.memory_usage)},
    )
    return item


def list_equipment(db: Session, params, *, tower_id, equipment_type, network_status):
    stmt = select(Equipment)
    if tower_id:
        stmt = stmt.where(Equipment.tower_id == tower_id)
    if equipment_type:
        stmt = stmt.where(Equipment.equipment_type == equipment_type)
    if network_status:
        stmt = stmt.where(Equipment.network_status == network_status)
    if params.q:
        like = f"%{params.q.strip()}%"
        stmt = stmt.where((Equipment.serial_number.ilike(like)) | (Equipment.model.ilike(like)))
    stmt = apply_sort(stmt, params.sort_by, params.sort_dir, {"created_at": Equipment.created_at, "serial_number": Equipment.serial_number})
    return paginate(db, stmt, params.page, params.page_size)


def maintenance_due(db: Session, within_days: int = 7):
    horizon = utcnow().date() + timedelta(days=within_days)
    rows = db.scalars(
        select(Equipment).where(
            Equipment.next_maintenance_date.is_not(None),
            Equipment.next_maintenance_date <= horizon,
        )
    ).all()
    return list(rows)


def _maintenance_notice(db: Session, item: Equipment) -> None:
    if item.next_maintenance_date is None or item.maintenance_notified:
        return
    if item.next_maintenance_date > utcnow().date() + timedelta(days=7):
        return
    item.maintenance_notified = True
    notify_roles(
        db,
        [Role.NETWORK_ENGINEER.value, Role.OPERATIONS_MANAGER.value],
        NotificationEvent.MAINTENANCE_DUE,
        "Maintenance due",
        f"Equipment {item.serial_number} is due for maintenance on {item.next_maintenance_date}.",
        {"equipment_id": str(item.id)},
    )


def _outage_query():
    return select(Outage).options(selectinload(Outage.towers), selectinload(Outage.affected))


def create_outage(db: Session, actor: User, data, background_tasks=None) -> Outage:
    if data.expected_resolution <= data.start_time:
        raise AppError("Expected resolution must be after the start time", 422, "invalid_outage")
    towers = []
    for tower_id in data.tower_ids:
        tower = _tower(db, tower_id)
        if tower.status == TowerStatus.DECOMMISSIONED.value:
            raise AppError(f"Tower {tower.tower_code} is decommissioned", 409, "tower_decommissioned")
        towers.append(tower)
    outage = Outage(
        code=next_code(db, "outage", "OUT"),
        title=data.title.strip(),
        description=data.description,
        outage_type=data.outage_type.value,
        severity=data.severity.value,
        status=OutageStatus.OPEN.value,
        start_time=_naive(data.start_time),
        expected_resolution=_naive(data.expected_resolution),
        created_by=actor.id,
    )
    outage.towers = towers
    db.add(outage)
    db.flush()
    affected = _snapshot_customers(db, outage, [tower.id for tower in towers])
    forced = TowerStatus.OFFLINE if data.severity in {Severity.HIGH, Severity.CRITICAL} else TowerStatus.MAINTENANCE
    for tower in towers:
        if tower.status != TowerStatus.DECOMMISSIONED.value:
            tower.status = forced.value
    payload = {
        "outage_id": str(outage.id),
        "code": outage.code,
        "severity": outage.severity,
        "tower_ids": [str(tower.id) for tower in towers],
        "affected_customer_ids": [str(row.customer_id) for row in affected],
    }
    for row in affected:
        customer = db.get(Customer, row.customer_id)
        if customer and customer.user_id:
            notify(
                db,
                customer.user_id,
                NotificationEvent.NETWORK_OUTAGE,
                f"Network outage {outage.code}",
                outage.title,
                payload,
            )
    notify_roles(
        db,
        [Role.NETWORK_ENGINEER.value],
        NotificationEvent.NETWORK_OUTAGE,
        f"Network outage {outage.code}",
        outage.title,
        payload,
    )
    log_action(db, actor_id=actor.id, action="outage.created", entity="outage", entity_id=outage.id, new=payload)
    _publish("outage.created", outage, payload)
    spawn(background_tasks)
    return db.scalar(_outage_query().where(Outage.id == outage.id))


def _snapshot_customers(db: Session, outage: Outage, tower_ids: list) -> list[OutageCustomer]:
    customer_ids = db.scalars(
        select(CustomerTower.customer_id)
        .join(Customer, Customer.id == CustomerTower.customer_id)
        .where(
            CustomerTower.tower_id.in_(tower_ids),
            Customer.deleted_at.is_(None),
            Customer.status == CustomerStatus.ACTIVE.value,
        )
    ).all()
    rows = []
    seen = set()
    for customer_id in customer_ids:
        if customer_id in seen:
            continue
        seen.add(customer_id)
        row = OutageCustomer(outage_id=outage.id, customer_id=customer_id)
        db.add(row)
        rows.append(row)
    db.flush()
    return rows


def change_outage_status(db: Session, actor: User, outage_id, new_status: OutageStatus, background_tasks=None) -> Outage:
    outage = db.scalar(_outage_query().where(Outage.id == outage_id))
    if outage is None:
        raise AppError("Outage not found", 404, "not_found")
    assert_transition(OUTAGE_TRANSITIONS, outage.status, new_status, "outage")
    outage.status = new_status.value
    log_action(
        db,
        actor_id=actor.id,
        action="outage.updated",
        entity="outage",
        entity_id=outage.id,
        new={"status": outage.status},
    )
    return outage


def resolve_outage(db: Session, actor: User, outage_id, actual_resolution, background_tasks=None) -> Outage:
    outage = db.scalar(_outage_query().where(Outage.id == outage_id))
    if outage is None:
        raise AppError("Outage not found", 404, "not_found")
    assert_transition(OUTAGE_TRANSITIONS, outage.status, OutageStatus.RESOLVED, "outage")
    actual = _naive(actual_resolution)
    if actual < outage.start_time:
        raise AppError("Resolution time cannot be before the outage started", 422, "invalid_outage")
    outage.status = OutageStatus.RESOLVED.value
    outage.actual_resolution = actual
    for tower in outage.towers:
        still_open = db.scalar(
            select(func.count())
            .select_from(Outage)
            .join(outage_towers, outage_towers.c.outage_id == Outage.id)
            .where(
                outage_towers.c.tower_id == tower.id,
                Outage.status != OutageStatus.RESOLVED.value,
                Outage.id != outage.id,
            )
        ) or 0
        if not still_open and tower.status != TowerStatus.DECOMMISSIONED.value:
            tower.status = TowerStatus.ACTIVE.value
    payload = {"outage_id": str(outage.id), "code": outage.code}
    for affected in outage.affected:
        customer = db.get(Customer, affected.customer_id)
        if customer and customer.user_id:
            notify(
                db,
                customer.user_id,
                NotificationEvent.SERVICE_RESTORED,
                f"Service restored {outage.code}",
                f"{outage.title} has been resolved.",
                payload,
            )
    notify_roles(
        db,
        [Role.NETWORK_ENGINEER.value],
        NotificationEvent.SERVICE_RESTORED,
        f"Service restored {outage.code}",
        outage.title,
        payload,
    )
    log_action(
        db,
        actor_id=actor.id,
        action="outage.resolved",
        entity="outage",
        entity_id=outage.id,
        new={"actual_resolution": actual.isoformat()},
    )
    _publish("outage.resolved", outage, payload)
    spawn(background_tasks)
    return outage


def list_outages(db: Session, actor: User, params, *, status, severity):
    stmt = _outage_query()
    if is_customer(actor):
        own = linked_customer(db, actor)
        if own is None:
            return [], 0
        stmt = stmt.where(Outage.id.in_(select(OutageCustomer.outage_id).where(OutageCustomer.customer_id == own.id)))
    if status:
        stmt = stmt.where(Outage.status == status)
    if severity:
        stmt = stmt.where(Outage.severity == severity)
    if params.q:
        like = f"%{params.q.strip()}%"
        stmt = stmt.where((Outage.title.ilike(like)) | (Outage.code.ilike(like)))
    stmt = apply_sort(stmt, params.sort_by, params.sort_dir, {"created_at": Outage.created_at, "start_time": Outage.start_time, "code": Outage.code})
    return paginate(db, stmt, params.page, params.page_size)


def get_outage(db: Session, actor: User, outage_id) -> Outage:
    outage = db.scalar(_outage_query().where(Outage.id == outage_id))
    if outage is None:
        raise AppError("Outage not found", 404, "not_found")
    if is_customer(actor):
        own = linked_customer(db, actor)
        if own is None or all(row.customer_id != own.id for row in outage.affected):
            raise AppError("Outage not found", 404, "not_found")
    return outage


def _publish(event: str, outage: Outage, payload: dict) -> None:
    from app.core.realtime import hub

    hub.publish({"event": event, **payload, "title": outage.title, "severity": outage.severity})


def _naive(value):
    if getattr(value, "tzinfo", None) is not None:
        return value.replace(tzinfo=None)
    return value
