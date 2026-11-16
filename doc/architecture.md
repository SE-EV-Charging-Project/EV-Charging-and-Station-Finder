# ChargeSlot Architecture

The first diagram shows the application components present in `chargeslot/backend`. The production target below it adds security and operations controls that are recommendations, not claims about the current implementation. Driver, operator, and administrator clients consume the API; no specific frontend implementation is assumed.

```mermaid
flowchart TB
    Clients["Driver / Operator / Admin clients"]
    ChargerNetwork["Charging station gateway / OCPP clients"]

    subgraph Backend["ChargeSlot FastAPI backend"]
        Entry["FastAPI application<br/>app/main.py"]
        Rest["REST API routers<br/>/api/v1"]
        WebSocket["Dashboard WebSocket router"]
        Gateway["OCPP gateway router<br/>/gateway"]

        subgraph Logic["Application and domain logic"]
            Services["Services<br/>auth, bookings, discovery,<br/>stations, vehicles, chargers, admin"]
            Domains["Domain modules<br/>booking, discovery, dashboard,<br/>gateway, auth, vehicles, stations"]
            Schemas["Pydantic schemas<br/>request and response validation"]
        end

        ORM["SQLAlchemy models and session"]
        Migrations["Alembic migrations"]
    end

    Database[("Relational database<br/>SQLite by default")]

    Clients -->|"HTTP / JSON"| Entry
    Clients <-->|"WebSocket dashboard updates"| WebSocket
    ChargerNetwork -->|"OCPP status events"| Gateway
    Entry --> Rest
    Rest --> Schemas
    Rest --> Services
    Services --> Domains
    Domains --> ORM
    Gateway --> Domains
    WebSocket --> Domains
    ORM <--> Database
    Migrations -->|"Create / upgrade schema"| Database
```

## Request and data flow

1. `app/main.py` creates the FastAPI application and mounts the versioned REST API, dashboard WebSocket router, and gateway routes.
2. REST endpoints validate input and output with Pydantic schemas and call application services for feature behavior.
3. Services and domain modules use the SQLAlchemy session and models to read or persist application data.
4. Gateway events update charger and connector state; dashboard clients can receive real-time updates over the WebSocket endpoint.
5. Alembic manages relational database schema changes. The default local database is SQLite, configurable using `DATABASE_URL`.

The backend exposes the interactive API docs at `/api/v1/docs` and a health check at `/health`.

## Security-aware production target

This is a phased target architecture. The FastAPI application and domain modules are in the repository; the edge controls, managed services, and operational controls shown here must be selected and implemented before production exposure.

```mermaid
flowchart TB
    Clients["Driver / Operator / Admin clients"]
    CP["Charge point gateways"]
    IdP["Identity provider<br/>optional future integration"]

    subgraph Edge["Public edge / trust boundary"]
        TLS["TLS termination"]
        WAF["WAF / DDoS protection"]
        Limits["Request size, rate and connection limits"]
    end

    subgraph Private["Private application network"]
        API["Stateless FastAPI replicas"]
        Auth["JWT validation, RBAC,<br/>resource ownership checks"]
        REST["REST endpoints"]
        WS["WebSocket endpoint<br/>origin checks + scoped auth"]
        OCPP["OCPP ingestion<br/>per-device credentials + replay checks"]
        Queue["Optional durable job queue"]
        Worker["Background workers"]
    end

    subgraph Data["Restricted data network"]
        DB[("Managed PostgreSQL<br/>private endpoint, encryption, backups")]
        Cache[("Optional Redis<br/>rate limits, cache, pub/sub")]
    end

    Secrets["Secrets manager / KMS"]
    Telemetry["Central logs, metrics, traces<br/>alerts; redact sensitive data"]
    CI["CI security checks<br/>tests, dependency + secret scanning"]

    Clients -->|"HTTPS"| TLS
    CP -->|"TLS + signed/device-authenticated OCPP"| TLS
    TLS --> WAF --> Limits --> API
    API --> Auth
    Auth --> REST
    Auth --> WS
    Auth --> OCPP
    REST --> DB
    OCPP --> DB
    REST -. "short-lived cache / rate limits" .-> Cache
    WS -. "multi-replica pub/sub when needed" .-> Cache
    OCPP -. "asynchronous work when needed" .-> Queue --> Worker
    Worker --> DB
    Secrets -. "rotated credentials" .-> API
    Secrets -. "database keys / credentials" .-> DB
    API --> Telemetry
    Worker --> Telemetry
    CI -. "release gate" .-> API
    IdP -. "OIDC integration if adopted" .-> API
```

### Security controls and rollout notes

- **Network and transport:** expose only the TLS-protected edge; keep the application, database, cache, and queue on private network paths. Restrict outbound access and administrative access.
- **Identity and authorization:** validate short-lived access tokens, enforce role and per-resource ownership checks on every protected operation, and test cross-user and cross-operator access. Keep signing keys outside source control and rotate them through a secrets manager.
- **WebSockets:** validate the browser origin and authorize access to each subscribed station. Prefer a short-lived, single-use connection ticket over putting a reusable bearer token in the URL; URLs commonly appear in access logs.
- **OCPP gateway:** replace the development shared secret with unique, revocable per-device credentials and signed messages with timestamps/nonces, replay protection, rotation, and rate limits. Allowlist network sources only where device networking supports it.
- **Data protection:** use a managed production database with encryption in transit and at rest, least-privilege database credentials, automated encrypted backups, and tested restores. Keep personal data and payment data out of logs; use a payment provider rather than storing card data.
- **Abuse and availability:** apply edge and application rate limits, payload and connection limits, request timeouts, and bounded WebSocket subscriptions. Avoid relying on in-process rate limits or event fan-out when running multiple replicas.
- **Operations:** centralize redacted security and service logs, monitor authentication failures and gateway anomalies, alert on service and database health, and rehearse credential rotation and incident response. Keep API documentation and debug features restricted outside development.
- **Delivery pipeline:** require automated tests for authorization boundaries, dependency and secret scanning, reviewed database migrations, and a release rollback path. Treat a security test failure as a release blocker.

See the [delivery and production-readiness plan](chargeslot-delivery-plan.md) for phase gates, measurable goals, and illustrative cost ranges.
