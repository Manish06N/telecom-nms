# Telecom Service & Network Management System

A FastAPI backend for a telecom operation: customers, plans, SIMs, devices, subscriptions, usage, towers, outages, technicians, tickets, SLAs, and the audit trail around all of them.

If you are new to FastAPI, read [LEARNING.md](LEARNING.md) before the code. It walks through one real request and then each day of the brief.

## Run it

Docker (API, PostgreSQL, Redis):

```bash
cd telecom-nms
docker compose up --build
```

Open http://localhost:8000/docs

Seeded super admin: `admin@telecom.local` / `Admin@12345`

The Swagger **Authorize** button uses `POST /api/v1/auth/token`. The username is the email. JSON clients use `POST /api/v1/auth/login`.

On a laptop without Docker:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

In `.env`, set `DATABASE_URL=sqlite:///./telecom.db` if PostgreSQL is not installed. Then:

```bash
alembic upgrade head
uvicorn app.main:app --reload
```

Optional Celery worker (the API already sends notifications with FastAPI background tasks):

```bash
docker compose --profile workers up --build
```

## Tests

```bash
pytest -q
```

Tests use an in-memory SQLite database. They do not need Docker.

## The demo, in order

This is the path the assignment asks you to show. The same path is `tests/integration/test_demo_flow.py` and `postman/Telecom-NMS.postman_collection.json`.

1. Admin login
2. Create a plan, then activate it (a draft cannot be sold)
3. Create a customer with a phone, a service address, and a login
4. Submit KYC, verify it, then activate the customer
5. Register a SIM and a device
6. Activate the SIM onto the customer, then install it in the device
7. Create a subscription and record usage
8. Register a tower and map the customer to it
9. Open an outage and read the affected-customer list
10. Customer creates a ticket
11. Assign an agent and a technician, start, resolve, close
12. Resolve the outage
13. Read the customer's notifications
14. Open the operations dashboard and a report
15. Read the audit log

## Where the code lives

| You want to understand… | Open |
| --- | --- |
| How a request enters | `app/main.py` |
| Who is allowed to try | `app/domain/permissions.py` |
| Which status change is legal | `app/domain/transitions.py` |
| Quota, SLA, IMEI rules with no database | `app/domain/` |
| The tables | `app/models/` |
| The business decisions | `app/services/` |
| The HTTP layer | `app/api/v1/endpoints/` |
| Request and response shapes | `app/schemas/contracts.py` |

Routes are thin on purpose. A route checks the role, then calls a service. The service is where "KYC must be verified" and "this SIM is already in a phone" live.

## Roles

| Role | What they are for |
| --- | --- |
| Super admin | Staff accounts, and every other action |
| Operations manager | Customers, plans, network, reports, SLA rules |
| Support agent | Customers and tickets. Cannot verify KYC |
| Network engineer | Towers, equipment, outages |
| Field technician | Jobs assigned to them, in their city, matching a skill |
| Customer | Their own profile, usage, tickets, and requests |

A role is not ownership. A customer has `customer:read`, and the service still hides every customer who is not them.

## Useful URLs

| URL | What it is |
| --- | --- |
| `/docs` | Swagger |
| `/health` | Database ping |
| `/metrics` | Prometheus |
| `/api/v1/dashboard/operations` | Operations totals |
| `/api/v1/operations/run-schedules` | Expire plans, mark SLA breaches, maintenance notices |
| `/ws/outages?token=ACCESS_TOKEN` | Live outage events |

Reports accept `export=csv` or `export=xlsx`.

Schema diagram: [docs/schema.md](docs/schema.md).
