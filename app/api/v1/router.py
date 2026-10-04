from fastapi import APIRouter

from app.api.v1.endpoints import auth, commerce, customers, insights, network, plans, support
from app.api.v1.endpoints.network import include_customer_tower

router = APIRouter()
router.include_router(auth.router)
router.include_router(auth.users)
router.include_router(customers.router)
include_customer_tower(router)
router.include_router(plans.router)
router.include_router(commerce.sims)
router.include_router(commerce.devices)
router.include_router(commerce.subscriptions)
router.include_router(commerce.usage)
router.include_router(network.towers)
router.include_router(network.equipment)
router.include_router(network.outages)
router.include_router(support.technicians)
router.include_router(support.tickets)
router.include_router(support.sla)
router.include_router(support.requests)
router.include_router(insights.dashboard)
router.include_router(insights.reports)
router.include_router(insights.audit)
router.include_router(insights.notifications)
router.include_router(insights.operations)
