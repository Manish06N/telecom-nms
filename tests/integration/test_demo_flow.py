"""The story the project has to be able to tell, plus the rules that make it more than CRUD."""

from datetime import datetime, timedelta, timezone

from app.domain.enums import Role
from app.domain.validators import luhn_valid
from app.models.audit import AuditLog
from sqlalchemy import select
from tests.conftest import auth_header, make_user


def utc_date() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def imei(prefix: str) -> str:
    base = prefix.ljust(14, "0")[:14]
    for digit in range(10):
        candidate = base + str(digit)
        if luhn_valid(candidate):
            return candidate
    raise RuntimeError(prefix)


def test_demo_flow(client, session, admin_headers):
    agent = make_user(session, "agent@telecom.local", Role.SUPPORT_AGENT)
    make_user(session, "engineer@telecom.local", Role.NETWORK_ENGINEER)
    agent_headers, _ = auth_header(client, "agent@telecom.local")

    plan = client.post(
        "/api/v1/plans",
        headers=admin_headers,
        json={
            "name": "Data 2GB",
            "description": "Prepaid data pack",
            "billing_type": "prepaid",
            "category": "data",
            "price": "199.00",
            "validity_days": 28,
            "data_limit_mb": 2048,
            "voice_limit_minutes": 0,
            "sms_limit": 100,
        },
    )
    assert plan.status_code == 201, plan.text
    plan_id = plan.json()["id"]
    bigger = client.post(
        "/api/v1/plans",
        headers=admin_headers,
        json={
            "name": "Data 5GB",
            "billing_type": "prepaid",
            "category": "combo",
            "price": "399.00",
            "validity_days": 28,
            "data_limit_mb": 5120,
            "voice_limit_minutes": 100,
            "sms_limit": 100,
        },
    )
    assert bigger.status_code == 201, bigger.text
    bigger_id = bigger.json()["id"]
    client.post(f"/api/v1/plans/{plan_id}/activate", headers=admin_headers)
    client.post(f"/api/v1/plans/{bigger_id}/activate", headers=admin_headers)
    compared = client.post("/api/v1/plans/compare", headers=admin_headers, json={"plan_ids": [plan_id, bigger_id]})
    assert compared.status_code == 200
    assert any("price differs" in line for line in compared.json()["differences"])

    customer = client.post(
        "/api/v1/customers",
        headers=admin_headers,
        json={
            "customer_type": "individual",
            "first_name": "Asha",
            "last_name": "Rao",
            "date_of_birth": "1998-04-12",
            "create_login": True,
            "email": "asha@example.com",
            "password": "AshaPass1",
            "contacts": [{"contact_type": "mobile", "value": "9876543210", "is_primary": True}],
            "addresses": [
                {
                    "address_type": "service",
                    "line1": "12 Lake Road",
                    "city": "Patna",
                    "state": "Bihar",
                    "postal_code": "800001",
                    "is_primary": True,
                }
            ],
        },
    )
    assert customer.status_code == 201, customer.text
    customer_id = customer.json()["id"]
    too_soon = client.post(f"/api/v1/customers/{customer_id}/activate", headers=admin_headers)
    assert too_soon.status_code == 400
    assert too_soon.json()["code"] == "kyc_required"
    client.post(f"/api/v1/customers/{customer_id}/kyc", headers=admin_headers, json={"status": "submitted"})
    verified = client.post(f"/api/v1/customers/{customer_id}/kyc", headers=admin_headers, json={"status": "verified"})
    assert verified.status_code == 200
    # A support agent is not allowed to verify KYC. This one is already verified; reject is also ops-only.
    agent_reject = client.post(
        f"/api/v1/customers/{customer_id}/kyc",
        headers=agent_headers,
        json={"status": "rejected", "note": "no"},
    )
    assert agent_reject.status_code == 403
    activated = client.post(f"/api/v1/customers/{customer_id}/activate", headers=admin_headers)
    assert activated.status_code == 200
    assert activated.json()["status"] == "active"

    sim = client.post(
        "/api/v1/sims",
        headers=admin_headers,
        json={"iccid": "89014103211118510720", "msisdn": "9876543210", "sim_type": "physical"},
    )
    assert sim.status_code == 201, sim.text
    sim_id = sim.json()["id"]
    assert sim.json()["msisdn"] == "+919876543210"
    spare = client.post(
        "/api/v1/sims",
        headers=admin_headers,
        json={"iccid": "89014103211118510721", "msisdn": "9876543211", "sim_type": "physical"},
    )
    spare_id = spare.json()["id"]
    duplicate = client.post(
        "/api/v1/sims",
        headers=admin_headers,
        json={"iccid": "89014103211118510720", "msisdn": "9123456780", "sim_type": "esim"},
    )
    assert duplicate.status_code == 409

    device_imei = imei("49015420323751")
    device = client.post(
        "/api/v1/devices",
        headers=admin_headers,
        json={"imei": device_imei, "model": "Nord", "manufacturer": "OnePlus", "device_type": "handset"},
    )
    assert device.status_code == 201, device.text
    device_id = device.json()["id"]
    again = client.post(
        "/api/v1/devices",
        headers=admin_headers,
        json={"imei": device_imei, "model": "Nord", "manufacturer": "OnePlus", "device_type": "handset"},
    )
    assert again.status_code == 409
    assert again.json()["code"] == "duplicate_imei"

    bad_map = client.post(f"/api/v1/devices/{device_id}/map-sim", headers=admin_headers, json={"sim_id": sim_id})
    assert bad_map.status_code == 409

    turned_on = client.post(f"/api/v1/sims/{sim_id}/activate", headers=admin_headers, json={"customer_id": customer_id})
    assert turned_on.status_code == 200
    mapped = client.post(f"/api/v1/devices/{device_id}/map-sim", headers=admin_headers, json={"sim_id": sim_id})
    assert mapped.status_code == 201, mapped.text

    subscription = client.post(
        "/api/v1/subscriptions",
        headers=admin_headers,
        json={"customer_id": customer_id, "sim_id": sim_id, "plan_id": plan_id},
    )
    assert subscription.status_code == 201, subscription.text
    subscription_id = subscription.json()["id"]
    upgraded = client.post(
        f"/api/v1/subscriptions/{subscription_id}/upgrade",
        headers=admin_headers,
        json={"plan_id": bigger_id},
    )
    assert upgraded.status_code == 200, upgraded.text
    downgrade_same = client.post(
        f"/api/v1/subscriptions/{subscription_id}/upgrade",
        headers=admin_headers,
        json={"plan_id": plan_id},
    )
    assert downgrade_same.status_code == 409

    usage = client.post(
        "/api/v1/usage",
        headers=admin_headers,
        json={"sim_id": sim_id, "usage_date": utc_date(), "data_mb": "100.5", "voice_minutes": "1", "sms_count": 2},
    )
    assert usage.status_code == 201, usage.text
    voice_blocked = client.post(
        "/api/v1/usage",
        headers=admin_headers,
        json={"sim_id": sim_id, "usage_date": utc_date(), "data_mb": "0", "voice_minutes": "5", "sms_count": 0},
    )
    # After upgrade the plan includes 100 voice minutes, so a small voice usage is allowed.
    assert voice_blocked.status_code == 201
    over = client.post(
        "/api/v1/usage",
        headers=admin_headers,
        json={"sim_id": sim_id, "usage_date": utc_date(), "data_mb": "6000", "voice_minutes": "0", "sms_count": 0},
    )
    assert over.status_code == 409
    assert over.json()["code"] == "quota_exceeded"
    util = client.get(f"/api/v1/usage/subscriptions/{subscription_id}/utilization", headers=admin_headers)
    assert util.status_code == 200
    assert util.json()["data"]["remaining"] is not None

    tower = client.post(
        "/api/v1/towers",
        headers=admin_headers,
        json={
            "name": "Patna Central",
            "tower_type": "macro",
            "latitude": "25.594100",
            "longitude": "85.137600",
            "address": "Gandhi Maidan",
            "city": "Patna",
            "state": "Bihar",
            "coverage_radius_km": "3.5",
            "capacity": 2,
        },
    )
    assert tower.status_code == 201, tower.text
    tower_id = tower.json()["id"]
    link = client.post(f"/api/v1/customers/{customer_id}/towers", headers=admin_headers, json={"tower_id": tower_id, "is_primary": True})
    assert link.status_code == 201, link.text

    start = utc_now()
    outage = client.post(
        "/api/v1/outages",
        headers=admin_headers,
        json={
            "title": "Fiber cut near Gandhi Maidan",
            "outage_type": "fiber_cut",
            "severity": "critical",
            "tower_ids": [tower_id],
            "start_time": start.isoformat(),
            "expected_resolution": (start + timedelta(hours=4)).isoformat(),
        },
    )
    assert outage.status_code == 201, outage.text
    assert customer_id in outage.json()["affected_customer_ids"]
    outage_id = outage.json()["id"]
    assert client.get(f"/api/v1/towers?q=Patna", headers=admin_headers).json()["items"][0]["status"] == "offline"

    customer_headers, _ = auth_header(client, "asha@example.com", "AshaPass1")
    ticket = client.post(
        "/api/v1/tickets",
        headers=customer_headers,
        json={"ticket_type": "network_issue", "subject": "No signal since morning", "description": "Phone shows no service in Gandhi Maidan.", "priority": "critical"},
    )
    assert ticket.status_code == 201, ticket.text
    ticket_id = ticket.json()["id"]
    assert ticket.json()["sla_deadline"] is not None

    tech = client.post(
        "/api/v1/technicians",
        headers=admin_headers,
        json={
            "email": "tech@telecom.local",
            "full_name": "Ravi Kumar",
            "password": "RaviPass1",
            "service_city": "Patna",
            "skills": ["fiber", "tower"],
        },
    )
    assert tech.status_code == 201, tech.text
    tech_id = tech.json()["id"]
    wrong_city = client.post(
        "/api/v1/technicians",
        headers=admin_headers,
        json={
            "email": "tech2@telecom.local",
            "full_name": "Other City",
            "password": "RaviPass1",
            "service_city": "Delhi",
            "skills": ["fiber"],
        },
    )
    assigned_bad = client.post(
        f"/api/v1/tickets/{ticket_id}/assign",
        headers=admin_headers,
        json={"agent_id": str(agent.id), "technician_id": wrong_city.json()["id"]},
    )
    assert assigned_bad.status_code == 409
    assert assigned_bad.json()["code"] == "outside_service_area"
    assigned = client.post(
        f"/api/v1/tickets/{ticket_id}/assign",
        headers=admin_headers,
        json={"agent_id": str(agent.id), "technician_id": tech_id},
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["status"] == "assigned"
    hidden = client.post(
        f"/api/v1/tickets/{ticket_id}/comments",
        headers=agent_headers,
        json={"body": "Site access needed", "is_internal": True},
    )
    assert hidden.status_code == 201
    customer_comments = client.get(f"/api/v1/tickets/{ticket_id}/comments", headers=customer_headers)
    assert customer_comments.json() == []
    client.post(f"/api/v1/tickets/{ticket_id}/start", headers=agent_headers)
    resolved = client.post(
        f"/api/v1/tickets/{ticket_id}/resolve",
        headers=agent_headers,
        json={"resolution_notes": "Spliced the fiber and confirmed signal."},
    )
    assert resolved.status_code == 200, resolved.text
    closed = client.post(f"/api/v1/tickets/{ticket_id}/close", headers=customer_headers)
    assert closed.status_code == 200

    restored = client.post(
        f"/api/v1/outages/{outage_id}/resolve",
        headers=admin_headers,
        json={"actual_resolution": (start + timedelta(hours=2)).isoformat()},
    )
    assert restored.status_code == 200
    notices = client.get("/api/v1/notifications", headers=customer_headers)
    assert notices.status_code == 200
    kinds = {item["event_type"] for item in notices.json()}
    assert "network_outage" in kinds
    assert "service_restored" in kinds

    dashboard = client.get("/api/v1/dashboard/operations", headers=admin_headers)
    assert dashboard.status_code == 200, dashboard.text
    body = dashboard.json()
    assert body["active_customers"] == 1
    assert body["active_subscriptions"] == 1
    assert body["open_tickets"] == 0

    growth = client.get("/api/v1/reports/customer-growth", headers=admin_headers)
    assert growth.status_code == 200
    assert growth.json()["total"] >= 1
    csv_report = client.get("/api/v1/reports/plan-popularity?export=csv", headers=admin_headers)
    assert "plan_code" in csv_report.text

    logs = client.get("/api/v1/audit-logs?entity=customer", headers=admin_headers)
    assert logs.status_code == 200
    actions = {item["action"] for item in logs.json()["items"]}
    assert "customer.created" in actions
    assert "customer.activated" in actions
    stored = session.scalars(select(AuditLog)).all()
    assert all("AshaPass1" not in str(row.new_value) for row in stored)

    # Complete a plan-change request back to the smaller pack. It is a downgrade.
    request = client.post(
        "/api/v1/service-requests",
        headers=customer_headers,
        json={
            "request_type": "plan_change",
            "subscription_id": subscription_id,
            "payload": {"new_plan_id": plan_id},
        },
    )
    assert request.status_code == 201, request.text
    request_id = request.json()["id"]
    for step in ("review", "approve", "start", "complete"):
        moved = client.post(f"/api/v1/service-requests/{request_id}/{step}", headers=admin_headers, json={"note": step})
        assert moved.status_code == 200, moved.text
    history = client.get(f"/api/v1/service-requests/{request_id}/history", headers=admin_headers)
    assert [item["to_status"] for item in history.json()] == [
        "submitted",
        "under_review",
        "approved",
        "in_progress",
        "completed",
    ]
    current = client.get(f"/api/v1/subscriptions/{subscription_id}", headers=admin_headers)
    assert current.json()["plan_id"] == plan_id

    # Spare SIM stays available and is not part of the story above; keep the id used.
    assert spare_id
