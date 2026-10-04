# Learn this project

You do not need to understand all 21 levels before the first file makes sense. The system repeats one pattern. Learn the pattern on login, then you can read any later feature.

## 1. What you are building

A telecom company has people, products, and hardware, and rules about how they move.

- A **customer** is a person or a company we bill.
- A **plan** is a product: prepaid or postpaid, with limits for data, voice, and SMS.
- A **SIM** is the card. Its **ICCID** is the serial printed on the card. Its **MSISDN** is the phone number people dial.
- A **device** is the phone or router. Its **IMEI** is the 15-digit identity of that hardware.
- A **subscription** is the contract that ties one customer, one SIM, and one plan together for a period of time.
- A **tower** is a radio site. Customers are mapped to a tower so an outage knows who lost service.
- A **ticket** is a support case. An **SLA** is the clock that says when that case is late.
- An **audit log** is the notebook that records who changed what.

## 2. A request walks through four rooms

Take `POST /api/v1/auth/login`.

1. **FastAPI** (`app/main.py`, then `app/api/v1/endpoints/auth.py`) reads the JSON and rejects a missing password before your code runs. That check is a **schema** in `app/schemas/contracts.py`.
2. The route calls `auth_service.login`. It does not hash passwords itself.
3. The **service** (`app/services/auth_service.py`) finds the user, checks the password, and refuses a deactivated account.
4. The **model** (`app/models/identity.py`) is the `users` table. SQLAlchemy turns that class into SQL.

If the service raises `AppError`, nothing is saved. `app/db/session.py` commits only when the request finishes cleanly. One request is one transaction. That is why completing a service request can change a subscription and write history together: if the plan change fails, the request does not stay "completed".

```
HTTP  ->  schema  ->  route  ->  service  ->  model  ->  database
                         |
                    permission check
```

`app/domain/` is the rule book that does not know HTTP or SQL. IMEI check digits, allowed status changes, SLA scoring, and quota math live there so they can be tested without a database. See `tests/unit/test_domain.py`.

## 3. Words FastAPI uses

**Path** is the URL. `/api/v1/customers/{customer_id}` is a path. `{customer_id}` is filled in by the caller.

**Schema** is a Pydantic class. It describes JSON. `CustomerCreate` is what the client sends. `CustomerRead` is what we send back. A schema is not a database table.

**Dependency** is `Depends(...)`. FastAPI runs it before your function. `get_db` opens a database session. `get_current_user` reads the token. `require(Permission.PLAN_WRITE)` stops a customer from creating a plan with HTTP 403.

**Status code** is the number in the response. 201 means created. 401 means "who are you?". 403 means "I know who you are, and you still cannot". 409 means the business rule refused, such as a duplicate IMEI. 422 means the JSON shape was wrong.

## 4. Day 1 — accounts, customers, plans

### Login is not "store the password"

`app/core/security.py` stores a **hash**. A hash is one-way. Login hashes the attempt and compares. The audit log records the email and role, never the password. `tests/integration/test_auth.py` checks that.

### Two tokens

| Token | Lifetime | Stored? | Used for |
| --- | --- | --- | --- |
| Access | 30 minutes | No | `Authorization: Bearer ...` on every call |
| Refresh | 7 days | Only as a SHA-256 hash | `POST /auth/refresh` to get a new pair |

The access token is not looked up. We trust the signature, then we **load the user from the database** and use the role stored there. If an admin deactivates you, the next call fails even if the token has not expired. See `get_current_user` in `app/api/deps.py`.

Refresh tokens rotate. Using an old rotated token again revokes every session. That commit is deliberate: a failed request normally rolls back, and this lockout has to remain. The comment is in `auth_service.refresh`.

Logout revokes one refresh token. The access token still works until it expires. That is normal. Keep the access token short.

Password reset: `POST /auth/password-reset/request` always says the same sentence, so strangers cannot learn which emails exist. In debug mode the response includes the token so you can practice. A real deployment would email it and leave it out of the JSON.

Public registration creates a **customer login** only. Staff accounts are `POST /api/v1/users`, and only a super admin can call it.

### A customer is not a user

`users` is the login. `customers` is the billing profile. They meet at `customers.user_id`. An admin can create a customer and, if `create_login` is true, a user at the same time.

Activation is a gate, not a boolean you flip:

- KYC must be `verified`
- there must be a primary mobile
- there must be a service address
- an individual must be 18, with a date of birth

A support agent can help with the profile. Only an operations manager or super admin can verify KYC. The customer cannot deactivate themselves through the status endpoint.

Deactivating a customer is refused while a subscription is still open. Archive (soft delete) is refused while the customer is still active. The row stays, with `deleted_at` set, because invoices and tickets must still point at someone.

### A plan is a product with a lifecycle

Create makes a **draft**. Drafts are not for sale. Activate makes it sellable. Deactivate stops new sales and leaves current subscribers alone. Only a draft that was never sold can be archived, because old subscriptions must still show the plan name.

Limits use three numbers:

| Value | Meaning |
| --- | --- |
| `0` | This plan does not include that service |
| `-1` | Unlimited |
| anything else | The cap for one billing cycle |

A data plan must have a data limit. A combo must include at least two of data, voice, and SMS. `POST /plans/compare` puts two to four plans side by side and lists the fields that differ.

Billing type and category cannot be edited after creation. If the product is a different kind of product, create a new plan.

## 5. Day 2 — SIM, device, subscription, usage

Allowed SIM moves are in `SIM_TRANSITIONS` inside `app/domain/transitions.py`. Available can become active. Active can be suspended, lost, blocked, or deactivated. Lost cannot quietly become active. The service calls `assert_transition`. There is no "set status to whatever you typed" endpoint that skips the map.

Activating a SIM requires an **active** customer. Installing a SIM in a device requires an **active** SIM that belongs to the same customer. A SIM can be in one device. A device can hold two SIMs. A duplicate IMEI is rejected, and the IMEI must pass the Luhn check (`app/domain/validators.py`).

The plan is not copied onto the SIM row. The subscription points at the SIM and the plan. If we copied the plan id onto the SIM, history would drift the moment someone upgraded. `GET /subscriptions?sim_id=` is the plan mapping.

Upgrade means a **higher price**. Downgrade means a **lower price**. You cannot jump between prepaid and postpaid on the same subscription. Renew starts a new cycle. Suspend blocks usage. If the cycle has already ended, reactivation is refused and the correct action is renew. Cancel ends the commercial relationship and leaves the SIM assigned until a termination request deactivates it.

Usage is stored as one row per SIM per day. Percent and remaining are sums across the current cycle, calculated in `app/domain/quotas.py`. Prepaid stops at the cap. Postpaid is allowed to go past it. At 80% we write a notification once per cycle.

## 6. Day 3 — towers and outages

`customer_towers` is the map from customer to tower. When an outage is opened, the affected customers are **copied** into `outage_customers`. If someone is mapped to the tower tomorrow, yesterday's outage does not change. High and critical outages mark the tower offline. Resolving the outage turns the tower active again when no other open outage still names it.

A tower at capacity refuses another customer. A decommissioned tower refuses an outage.

Technicians have skills and a service city. A fiber ticket in Patna cannot be given to a SIM-only technician, or to a fiber technician whose city is Delhi. Pending jobs are tickets still assigned to them. Completing the last job sets them back to available.

`/ws/outages?token=...` pushes outage events to whoever is connected. The HTTP handlers are synchronous and the socket is async, so `app/core/realtime.py` hops threads with `call_soon_threadsafe`. You can ignore that file until the rest feels comfortable.

## 7. Day 4 — tickets, SLA, requests, notifications

Ticket statuses are a map, same idea as SIMs:

`open → assigned → in_progress → resolved → closed`

You cannot resolve an open ticket. Someone has to start it. Internal comments are hidden from the customer.

The SLA deadline is not typed by the agent. `app/domain/sla.py` scores policies. A policy that names the ticket type beats a policy that only names the priority. The deadline is `opened at + resolution minutes`. `GET /api/v1/sla/watch` lists tickets that are already late and tickets that will be late soon. `POST /api/v1/operations/run-schedules` marks breaches, expires subscriptions, and warns about maintenance. Escalating a ticket raises priority. It does not move the deadline.

A service request is a queue: submitted, under review, approved, in progress, completed. The SIM replacement, number change, or plan change runs **when it is completed**, inside the same transaction. If the new SIM is no longer available, the request does not become completed.

Notifications are rows. A background task marks them delivered after the response. That is `BackgroundTasks` in the route, `spawn()` in `app/services/records.py`. Celery is optional and calls the same schedule function.

## 8. Day 5 — dashboard, reports, audit, safety

The dashboard is counts: active customers, open tickets, tower status, and so on. If `REDIS_URL` is set, that JSON is cached for 30 seconds. If Redis is down or blank, the API asks the database. The database remains the source of truth.

Reports take a date range and ignore filters that do not apply. `sort_by` is an allow-list, not a string pasted into SQL. That is how you avoid someone sorting by `name; drop table`.

Every important change writes `audit_logs` with the actor, the action, the entity, the previous value, and the new value. Passwords and tokens are not fields on that snapshot.

Other safety pieces you can point at in a review:

- passwords hashed with bcrypt
- role checks in `app/domain/permissions.py`, plus row checks in services
- rate limit in `app/middleware/rate_limit.py` (stricter on login)
- soft delete on customers and plans
- indexes on codes, status, email, IMEI, ICCID, MSISDN
- `/health` and `/metrics`

## 9. How to study, in order

1. `app/main.py` — the app object is small on purpose
2. `app/api/v1/endpoints/auth.py` and `app/services/auth_service.py`
3. `app/domain/transitions.py` — read one map out loud
4. `app/services/customer_service.py` — the activation gate
5. `app/services/plan_service.py` and `app/domain/quotas.py`
6. `tests/integration/test_demo_flow.py` — the whole story as code
7. Then the service whose name matches the feature you are revising

When a test fails, read the JSON `code` field (`kyc_required`, `quota_exceeded`, `invalid_transition`). That string is the rule that fired.

## 10. What "not just CRUD" means here

Creating a row is the easy part. The assignment is the rules around the row:

- illegal status changes return 409
- a plan cannot be sold while it is a draft
- a SIM from another customer cannot go into this phone
- an outage remembers who was affected at that moment
- a late ticket is late even if nobody clicked a special "breach" button, once the schedule runs
- a failed completion does not leave a half-applied plan change

If you add a feature later, put the rule in a service or in `app/domain/`, and add a test that tries the illegal move.
