# Database shape

The SQLAlchemy models in `app/models/` are the schema. `alembic/versions/0001_initial.py` creates every table from those models.

```mermaid
erDiagram
    users ||--o| customers : "login"
    users ||--o{ refresh_tokens : has
    customers ||--o{ customer_contacts : has
    customers ||--o{ customer_addresses : has
    customers ||--o{ customer_events : history
    customers }o--o{ towers : "customer_towers"
    customers ||--o{ sims : owns
    customers ||--o{ devices : owns
    customers ||--o{ subscriptions : holds
    customers ||--o{ tickets : opens
    service_plans ||--o{ subscriptions : "sold as"
    sims ||--o{ subscriptions : carries
    sims ||--o{ device_sim_mappings : installed
    devices ||--o{ device_sim_mappings : holds
    subscriptions ||--o{ subscription_events : history
    subscriptions ||--o{ usage_daily : usage
    towers ||--o{ equipment : hosts
    towers }o--o{ outages : "outage_towers"
    outages ||--o{ outage_customers : "snapshot"
    customers ||--o{ outage_customers : affected
    users ||--o| technicians : "is"
    technicians ||--o{ technician_skills : has
    technicians ||--o{ tickets : "field jobs"
    tickets ||--o{ ticket_comments : has
    tickets ||--o{ ticket_events : history
    sla_policies ||--o{ tickets : clocks
    customers ||--o{ service_requests : asks
    service_requests ||--o{ service_request_events : history
    users ||--o{ notifications : receives
    users ||--o{ audit_logs : performs
```

A few decisions that are easy to miss:

- The plan on a SIM is the open **subscription**, not a second copy of `plan_id` on `sims`.
- `outage_customers` is a snapshot taken when the outage opens.
- `usage_daily` is one row per SIM per date. Monthly totals are a sum.
- Customers and plans use `deleted_at` (soft delete). A SIM uses the status `deactivated` instead, because that word is the business state.
- Quota columns: `0` means not included, `-1` means unlimited.
