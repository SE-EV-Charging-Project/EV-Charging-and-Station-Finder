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

## 17. Security Measures Implemented

| Security Domain / Layer | Architectural Threat / Risk Mitigated | Technical Security Controls Implemented | Traceability / Enforcement |
| :--- | :--- | :--- | :--- |
| **Identity & Authentication** | Credential stuffing, brute-force, dictionary attacks, token theft | • Bcrypt salted hashing (cost factor 12) with zero plaintext persistence.<br>• Password complexity policy (min 8 chars, uppercase, lowercase, digit, symbol).<br>• Account lockout after 5 consecutive failed logins for 15-minute cooldown.<br>• Short-lived HS256 JWT access tokens (30m) with 7-day refresh token rotation. | `REQ-F1-02`<br>`REQ-F1-04`<br>`REQ-F1-05`<br>`HLD §Auth` |
| **Access Control & RBAC** | Privilege escalation, unauthorized vehicle edits, operator data leak | • Strict server-side role dependency injection (`get_current_user`) for Driver, Operator, Admin.<br>• Driver vehicle ownership isolation: non-admin drivers cannot access foreign vehicles.<br>• Multi-tenant operator data scope: station managers strictly isolated to their own stations.<br>• Auto-provisioning of starter EV ensures new drivers book safely without cross-tenant access. | `REQ-F1-10`<br>`REQ-F1-11`<br>`REQ-F1-12`<br>`REQ-F1-26` |
| **Payments & Billing** | Card credential exposure, replay webhooks, duplicate charges | • Zero raw card storage: hosted checkout offloading PAN handling to Razorpay (reduced PCI scope).<br>• Cryptographic HMAC-SHA256 signature verification on incoming payment webhooks.<br>• Idempotent transaction settlement enforcing atomic `PENDING` → `COMPLETED` transitions.<br>• Deterministic PDF tax invoice generation permanently snapshotting tariff and energy readings. | `REQ-F4-01`<br>`REQ-F4-04`<br>`ADR-04`<br>`HLD §Billing` |
| **Slot Booking Concurrency** | Double-booking, slot race conditions, vehicle reservation overlaps | • Database-level transaction locks (`SELECT FOR UPDATE`) on station and slot allocation.<br>• 5-minute temporary slot hold with automatic TTL expiration releasing stale reservations.<br>• Vehicle overlap prevention: blocks concurrent active reservations for the same vehicle.<br>• Automated status sync: expired slot timers restore map marker dot colors back to Available. | `REQ-F3-11`<br>`REQ-F3-12`<br>`REQ-F3-16`<br>`ADR-02` |
| **Geospatial & Input Security** | SQL injection, coordinate tampering, DoS radius scans | • Strict Pydantic v2 input validation with type constraints, bounds checking, and schema sanitization.<br>• SQLAlchemy 2.0 ORM parameterized statements preventing all SQL injection vectors.<br>• Bounded Haversine radius queries (1 to 50 km) preventing unbounded geospatial resource exhaustion.<br>• Path traversal security blocking directory escape attempts (`../`) on static web asset delivery. | `REQ-F2-01`<br>`REQ-F2-04`<br>`HLD §Stations`<br>`FastAPI DI` |
| **Network & Transport** | Man-in-the-Middle (MitM), eavesdropping, packet sniffing | • Enforced HTTPS / TLS encryption on all client-to-server and gateway communications.<br>• Secrets management: zero credentials in Git repository; loaded exclusively from runtime env.<br>• Generic authentication failure messages to prevent user enumeration / username harvesting.<br>• Cross-Origin Resource Sharing (CORS) restricted to authorized client origins. | `REQ-F1-09`<br>`§6 Deployment`<br>`§12 Cross-Cut` |
| **Audit & Compliance** | Non-repudiation failures, unmonitored security events | • Structured immutable audit logging (`AuditService.log_action`) capturing user ID, action, resource, IP.<br>• Security audit events logged for registration, login, lockout, password changes, and slot claims.<br>• Sensitive credential and token redaction from server logs and telemetry streams.<br>• Automated regression test gates (`pytest`, `testclient`) enforcing security invariants in CI pipeline. | `REQ-F1-14`<br>`§12 Cross-Cut`<br>`TC-F1-14`<br>`CI Gates` |

