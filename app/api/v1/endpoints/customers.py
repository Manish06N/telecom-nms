import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import PageParams, as_page, require
from app.db.session import get_db
from app.domain.enums import CustomerType, KycStatus, Permission
from app.schemas.contracts import (
    AddressIn,
    AddressRead,
    ContactIn,
    ContactRead,
    CustomerCreate,
    CustomerEventRead,
    CustomerRead,
    CustomerUpdate,
    KycUpdate,
    Page,
)
from app.services import customer_service

router = APIRouter(prefix="/customers", tags=["Customers"])


@router.post("", response_model=CustomerRead, status_code=201)
def create_customer(body: CustomerCreate, user=Depends(require(Permission.CUSTOMER_WRITE)), db: Session = Depends(get_db)):
    return customer_service.create_customer(db, user, body)


@router.get("", response_model=Page[CustomerRead])
def list_customers(
    params: PageParams = Depends(),
    status: str | None = None,
    kyc_status: KycStatus | None = None,
    customer_type: CustomerType | None = None,
    city: str | None = None,
    user=Depends(require(Permission.CUSTOMER_READ)),
    db: Session = Depends(get_db),
):
    rows, total = customer_service.list_customers(
        db,
        user,
        params,
        status=status,
        kyc_status=kyc_status.value if kyc_status else None,
        customer_type=customer_type.value if customer_type else None,
        city=city,
    )
    return as_page(rows, total, params)


@router.get("/{customer_id}", response_model=CustomerRead)
def get_customer(customer_id: uuid.UUID, user=Depends(require(Permission.CUSTOMER_READ)), db: Session = Depends(get_db)):
    return customer_service.get_customer(db, user, customer_id)


@router.patch("/{customer_id}", response_model=CustomerRead)
def update_customer(
    customer_id: uuid.UUID,
    body: CustomerUpdate,
    user=Depends(require(Permission.CUSTOMER_WRITE)),
    db: Session = Depends(get_db),
):
    return customer_service.update_profile(db, user, customer_id, body)


@router.post("/{customer_id}/contacts", response_model=ContactRead, status_code=201)
def add_contact(
    customer_id: uuid.UUID,
    body: ContactIn,
    user=Depends(require(Permission.CUSTOMER_WRITE)),
    db: Session = Depends(get_db),
):
    return customer_service.add_contact(db, user, customer_id, body)


@router.post("/{customer_id}/addresses", response_model=AddressRead, status_code=201)
def add_address(
    customer_id: uuid.UUID,
    body: AddressIn,
    user=Depends(require(Permission.CUSTOMER_WRITE)),
    db: Session = Depends(get_db),
):
    return customer_service.add_address(db, user, customer_id, body)


@router.post("/{customer_id}/kyc", response_model=CustomerRead)
def update_kyc(
    customer_id: uuid.UUID,
    body: KycUpdate,
    user=Depends(require(Permission.CUSTOMER_WRITE)),
    db: Session = Depends(get_db),
):
    return customer_service.update_kyc(db, user, customer_id, body.status, body.note)


@router.post("/{customer_id}/activate", response_model=CustomerRead)
def activate(customer_id: uuid.UUID, user=Depends(require(Permission.CUSTOMER_WRITE)), db: Session = Depends(get_db)):
    return customer_service.set_customer_status(db, user, customer_id, True)


@router.post("/{customer_id}/deactivate", response_model=CustomerRead)
def deactivate(customer_id: uuid.UUID, user=Depends(require(Permission.CUSTOMER_WRITE)), db: Session = Depends(get_db)):
    return customer_service.set_customer_status(db, user, customer_id, False)


@router.get("/{customer_id}/history", response_model=list[CustomerEventRead])
def history(customer_id: uuid.UUID, user=Depends(require(Permission.CUSTOMER_READ)), db: Session = Depends(get_db)):
    return customer_service.history(db, user, customer_id)


@router.delete("/{customer_id}", status_code=204)
def archive(customer_id: uuid.UUID, user=Depends(require(Permission.CUSTOMER_WRITE)), db: Session = Depends(get_db)):
    customer_service.soft_delete(db, user, customer_id)
