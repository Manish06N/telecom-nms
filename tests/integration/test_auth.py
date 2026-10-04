from tests.conftest import auth_header, make_user
from app.domain.enums import Role
from app.models.audit import AuditLog
from sqlalchemy import select


def test_register_login_me_refresh_and_logout(client):
    registered = client.post(
        "/api/v1/auth/register",
        json={"email": "asha@example.com", "full_name": "Asha Rao", "password": "AshaPass1"},
    )
    assert registered.status_code == 201, registered.text
    tokens = registered.json()["tokens"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert me.status_code == 200
    assert me.json()["role"] == "customer"
    assert "hashed_password" not in me.text

    refreshed = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refreshed.status_code == 200, refreshed.text
    new_tokens = refreshed.json()
    reused = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert reused.status_code == 401
    assert reused.json()["code"] == "token_reuse"
    # Reuse revoked the rotated session too.
    again = client.post("/api/v1/auth/refresh", json={"refresh_token": new_tokens["refresh_token"]})
    assert again.status_code == 401


def test_password_reset_and_deactivation(client, session, admin_headers):
    client.post(
        "/api/v1/auth/register",
        json={"email": "rita@example.com", "full_name": "Rita", "password": "RitaPass1"},
    )
    requested = client.post("/api/v1/auth/password-reset/request", json={"email": "rita@example.com"})
    assert requested.status_code == 200
    token = requested.json()["reset_token"]
    confirmed = client.post("/api/v1/auth/password-reset/confirm", json={"token": token, "new_password": "RitaPass2"})
    assert confirmed.status_code == 200
    old = client.post("/api/v1/auth/login", json={"email": "rita@example.com", "password": "RitaPass1"})
    assert old.status_code == 401
    new = client.post("/api/v1/auth/login", json={"email": "rita@example.com", "password": "RitaPass2"})
    assert new.status_code == 200

    missing = client.post("/api/v1/auth/password-reset/request", json={"email": "nobody@example.com"})
    assert missing.status_code == 200
    assert missing.json().get("reset_token") is None

    user_id = new.json() and client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new.json()['access_token']}"}).json()["id"]
    deactivated = client.post(f"/api/v1/users/{user_id}/deactivate", headers=admin_headers)
    assert deactivated.status_code == 200
    blocked = client.post("/api/v1/auth/login", json={"email": "rita@example.com", "password": "RitaPass2"})
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "account_inactive"


def test_customer_cannot_create_a_plan(client, session):
    make_user(session, "cust@example.com", Role.CUSTOMER)
    headers, _ = auth_header(client, "cust@example.com")
    response = client.post(
        "/api/v1/plans",
        headers=headers,
        json={
            "name": "Sneaky",
            "billing_type": "prepaid",
            "category": "data",
            "price": "10",
            "validity_days": 28,
            "data_limit_mb": 100,
        },
    )
    assert response.status_code == 403


def test_login_audit_does_not_store_the_password(client, session, admin_headers):
    rows = session.scalars(select(AuditLog).where(AuditLog.action == "auth.login")).all()
    blob = str([row.new_value for row in rows])
    assert "Admin@12345" not in blob
    assert "hashed_password" not in blob
