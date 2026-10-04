"""Importing this package registers every table on Base.metadata."""

from app.models.audit import AuditLog
from app.models.catalog import ServicePlan
from app.models.customer import Customer, CustomerAddress, CustomerContact, CustomerEvent, CustomerTower
from app.models.identity import PasswordResetToken, RefreshToken, Sequence, User
from app.models.inventory import Device, DeviceSimMapping, Sim, SimReplacement
from app.models.network import Equipment, Outage, OutageCustomer, Tower
from app.models.operations import (
    Notification,
    ServiceRequest,
    ServiceRequestEvent,
    SlaPolicy,
    Technician,
    TechnicianSkill,
    Ticket,
    TicketComment,
    TicketEvent,
)
from app.models.subscription import Subscription, SubscriptionEvent, UsageDaily

__all__ = [
    "AuditLog",
    "Customer",
    "CustomerAddress",
    "CustomerContact",
    "CustomerEvent",
    "CustomerTower",
    "Device",
    "DeviceSimMapping",
    "Equipment",
    "Notification",
    "Outage",
    "OutageCustomer",
    "PasswordResetToken",
    "RefreshToken",
    "Sequence",
    "ServicePlan",
    "ServiceRequest",
    "ServiceRequestEvent",
    "Sim",
    "SimReplacement",
    "SlaPolicy",
    "Subscription",
    "SubscriptionEvent",
    "Technician",
    "TechnicianSkill",
    "Ticket",
    "TicketComment",
    "TicketEvent",
    "Tower",
    "UsageDaily",
    "User",
]
