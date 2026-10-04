import uuid

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.api.deps import PageParams, as_page, require
from app.db.session import get_db
from app.domain.enums import EquipmentType, NetworkLinkStatus, OutageStatus, Permission, Severity, TowerStatus, TowerType
from app.models.network import Outage
from app.schemas.contracts import (
    EquipmentCreate,
    EquipmentRead,
    Heartbeat,
    OutageCreate,
    OutageRead,
    OutageStatusBody,
    Page,
    ResolveOutage,
    TowerCreate,
    TowerLink,
    TowerRead,
    TowerStatusBody,
    TowerUpdate,
)
from app.services import network_service

towers = APIRouter(prefix="/towers", tags=["Network towers"])
equipment = APIRouter(prefix="/equipment", tags=["Network equipment"])
outages = APIRouter(prefix="/outages", tags=["Outages"])


def present_outage(outage: Outage) -> dict:
    return {
        "id": outage.id,
        "code": outage.code,
        "title": outage.title,
        "description": outage.description,
        "outage_type": outage.outage_type,
        "severity": outage.severity,
        "status": outage.status,
        "start_time": outage.start_time,
        "expected_resolution": outage.expected_resolution,
        "actual_resolution": outage.actual_resolution,
        "towers": [
            {"id": tower.id, "tower_code": tower.tower_code, "name": tower.name, "city": tower.city, "status": tower.status}
            for tower in outage.towers
        ],
        "affected_customer_ids": [row.customer_id for row in outage.affected],
    }


@towers.post("", response_model=TowerRead, status_code=201)
def create_tower(body: TowerCreate, user=Depends(require(Permission.TOWER_WRITE)), db: Session = Depends(get_db)):
    return network_service.create_tower(db, user, body)


@towers.get("", response_model=Page[TowerRead])
def list_towers(
    params: PageParams = Depends(),
    status: TowerStatus | None = None,
    city: str | None = None,
    tower_type: TowerType | None = None,
    user=Depends(require(Permission.TOWER_READ)),
    db: Session = Depends(get_db),
):
    rows, total = network_service.list_towers(
        db, params, status=status.value if status else None, city=city, tower_type=tower_type.value if tower_type else None
    )
    return as_page(rows, total, params)


@towers.patch("/{tower_id}", response_model=TowerRead)
def update_tower(tower_id: uuid.UUID, body: TowerUpdate, user=Depends(require(Permission.TOWER_WRITE)), db: Session = Depends(get_db)):
    return network_service.update_tower(db, user, tower_id, body)


@towers.post("/{tower_id}/status", response_model=TowerRead)
def tower_status(tower_id: uuid.UUID, body: TowerStatusBody, user=Depends(require(Permission.TOWER_WRITE)), db: Session = Depends(get_db)):
    return network_service.set_tower_status(db, user, tower_id, body.status)


@equipment.post("", response_model=EquipmentRead, status_code=201)
def register_equipment(
    body: EquipmentCreate,
    background: BackgroundTasks,
    user=Depends(require(Permission.TOWER_WRITE)),
    db: Session = Depends(get_db),
):
    item = network_service.register_equipment(db, user, body)
    from app.services.records import spawn

    spawn(background)
    return item


@equipment.get("", response_model=Page[EquipmentRead])
def list_equipment(
    params: PageParams = Depends(),
    tower_id: uuid.UUID | None = None,
    equipment_type: EquipmentType | None = None,
    network_status: NetworkLinkStatus | None = None,
    user=Depends(require(Permission.TOWER_READ)),
    db: Session = Depends(get_db),
):
    rows, total = network_service.list_equipment(
        db,
        params,
        tower_id=tower_id,
        equipment_type=equipment_type.value if equipment_type else None,
        network_status=network_status.value if network_status else None,
    )
    return as_page(rows, total, params)


@equipment.get("/maintenance-due", response_model=list[EquipmentRead])
def maintenance_due(within_days: int = 7, user=Depends(require(Permission.TOWER_READ)), db: Session = Depends(get_db)):
    return network_service.maintenance_due(db, within_days)


@equipment.post("/{equipment_id}/heartbeat", response_model=EquipmentRead)
def heartbeat(equipment_id: uuid.UUID, body: Heartbeat, user=Depends(require(Permission.TOWER_WRITE)), db: Session = Depends(get_db)):
    return network_service.heartbeat(db, user, equipment_id, body)


@outages.post("", response_model=OutageRead, status_code=201)
def create_outage(
    body: OutageCreate,
    background: BackgroundTasks,
    user=Depends(require(Permission.OUTAGE_WRITE)),
    db: Session = Depends(get_db),
):
    return present_outage(network_service.create_outage(db, user, body, background))


@outages.get("", response_model=Page[OutageRead])
def list_outages(
    params: PageParams = Depends(),
    status: OutageStatus | None = None,
    severity: Severity | None = None,
    user=Depends(require(Permission.OUTAGE_READ)),
    db: Session = Depends(get_db),
):
    rows, total = network_service.list_outages(db, user, params, status=status.value if status else None, severity=severity.value if severity else None)
    return as_page([present_outage(row) for row in rows], total, params)


@outages.get("/{outage_id}", response_model=OutageRead)
def get_outage(outage_id: uuid.UUID, user=Depends(require(Permission.OUTAGE_READ)), db: Session = Depends(get_db)):
    return present_outage(network_service.get_outage(db, user, outage_id))


@outages.post("/{outage_id}/status", response_model=OutageRead)
def outage_status(
    outage_id: uuid.UUID,
    body: OutageStatusBody,
    user=Depends(require(Permission.OUTAGE_WRITE)),
    db: Session = Depends(get_db),
):
    return present_outage(network_service.change_outage_status(db, user, outage_id, body.status))


@outages.post("/{outage_id}/resolve", response_model=OutageRead)
def resolve_outage(
    outage_id: uuid.UUID,
    body: ResolveOutage,
    background: BackgroundTasks,
    user=Depends(require(Permission.OUTAGE_WRITE)),
    db: Session = Depends(get_db),
):
    return present_outage(network_service.resolve_outage(db, user, outage_id, body.actual_resolution, background))


def include_customer_tower(parent: APIRouter) -> None:
    @parent.post("/customers/{customer_id}/towers", status_code=201, tags=["Network towers"])
    def map_tower(
        customer_id: uuid.UUID,
        body: TowerLink,
        user=Depends(require(Permission.TOWER_WRITE)),
        db: Session = Depends(get_db),
    ):
        link = network_service.map_customer_tower(db, user, customer_id, body.tower_id, body.is_primary)
        return {"customer_id": link.customer_id, "tower_id": link.tower_id, "is_primary": link.is_primary}
