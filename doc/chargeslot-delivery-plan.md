# ChargeSlot Delivery and Production-Readiness Plan

**Purpose:** move the existing ChargeSlot backend from a development-oriented MVP toward a secure, measurable, cost-controlled pilot and then a scalable service.

> **Planning assumptions:** the repository contains a FastAPI/SQLAlchemy backend, SQLite is the local default, and no production provider, region, traffic profile, deployment platform, or compliance scope has been selected. Cost figures below are rough USD planning ranges, not quotes. Validate them against a provider calculator and actual workload before purchase.

## Executive recommendation

Keep the application as a modular monolith for the pilot. Deploy stateless API instances behind a managed TLS/WAF edge, use managed PostgreSQL for production data, and keep the database and supporting services private. Add Redis, a durable queue, and separate workers only when measured multi-instance WebSocket fan-out, hot reads, or slow external work justify them. Do not start with Kubernetes or split the domain into microservices.

The production architecture is security-aware by design, but most infrastructure controls in the diagram are planned additions. Do not treat the diagram as evidence that those controls are already deployed.

## Priority outcomes

1. **Security:** protect identities, vehicle/location data, station/operator data, and gateway telemetry with layered controls and verifiable access boundaries.
2. **Performance:** measure real endpoints and telemetry flows; set and test service-level objectives before scaling.
3. **Reliability:** use recoverable production data storage, observable services, and tested restore/release procedures.
4. **Cost control:** start with the smallest managed footprint that meets the pilot's risk requirements; scale from telemetry and load-test evidence.
5. **Maintainability:** preserve a modular monolith and automate release checks rather than adding operational complexity prematurely.

## Target architecture

- **Edge:** managed DNS, TLS, WAF/DDoS protection, request-size limits, rate limiting, and health-based routing.
- **Application:** two stateless FastAPI replicas for a production pilot where availability requires node-failure tolerance; separate REST, dashboard WebSocket, and OCPP policies. Keep authorization in the application and verify resource ownership on every operation.
- **Data:** managed PostgreSQL in a private network, encrypted connections and storage, least-privilege credentials, automated backups, and point-in-time recovery where available.
- **Optional shared services:** Redis for distributed rate limiting/cache/WebSocket pub-sub and a durable queue for retryable or slow background work. Add these only for a demonstrated need.
- **Security operations:** managed secret storage/key management, centralized redacted logs, metrics/traces, alerting, dependency and secret scanning, and a tested incident/restore runbook.

See [architecture.md](architecture.md) for current and target diagrams and the security design notes.

## Phased implementation plan

### Phase 0 — Baseline and decisions (week 0–1)

- Name a service owner and data owner; document deployment region, expected pilot traffic, data retention, and recovery objectives.
- Inventory routes, roles, data fields, external integrations, secrets, database migration state, and current deployment assumptions.
- Capture baseline latency and database query behavior for discovery, live status, booking, and gateway ingestion.
- Confirm pilot spend ceiling and select provider/database options using a calculator; record assumptions and cost alerts.

**Exit gate:** an agreed pilot profile, threat/data inventory, service objectives, target spend, and deployment decision record.

### Phase 1 — Secure production foundation (weeks 1–3)

- Replace SQLite for production with managed PostgreSQL; validate all Alembic migrations and rollback/forward recovery in staging.
- Move secrets out of defaults and environment files committed to source. Use managed secret storage, separate credentials by environment, and rotate signing and gateway credentials.
- Enforce TLS; place application and database on private network paths; restrict ingress and egress.
- Require short-lived access credentials, explicit token validation, password hashing, server-side RBAC, and driver/operator resource scoping. Add tests for denied cross-tenant access.
- Replace the shared OCPP webhook secret with unique revocable device credentials and authenticated, timestamped messages with replay protection. Define credential bootstrap and rotation.
- For WebSockets, verify origin and station authorization. Replace long-lived query-string bearer tokens with short-lived single-use tickets or another transport that does not put reusable credentials in URLs.
- Add edge/application rate limits, request and body limits, connection limits, timeouts, safe error responses, and security headers at the edge.
- Keep API docs/debug access restricted to development or authenticated operators in production.

**Exit gate:** no default production secrets; encrypted transport and storage; successful authorization-abuse tests; tested gateway replay rejection; security review of externally exposed routes; private database reachability.

### Phase 2 — Performance and resilience pilot (weeks 3–5)

- Add structured logs with correlation IDs and redaction, request/error/latency metrics, database pool metrics, and alerting. Avoid logging tokens, passwords, precise location histories, or payment data.
- Add indexes from query plans and observed workloads; cap pagination and history queries; define statement and request timeouts.
- Run representative load tests at 2x expected peak pilot load, including simultaneous dashboard connections and OCPP status bursts.
- Confirm graceful overload behavior: reject or shed excess work predictably, preserve gateway events where required, and avoid unbounded queues or WebSocket fan-out.
- Configure automated encrypted database backups. Perform a restore drill and record actual recovery time and data-loss window.
- Use at least two application replicas only if the pilot's availability target requires instance-failure tolerance; verify health checks and rolling deploy/rollback.

**Exit gate:** measured objectives met at target load; restore drill meets agreed recovery objectives; dashboards and actionable alerts work; rollback procedure tested.

### Phase 3 — Controlled pilot and optimization (weeks 5–8)

- Release to a limited cohort with feature flags and a rollback window. Monitor sign-in failures, authorization denials, booking failures, OCPP freshness, API latency, database saturation, and cost.
- Review spend weekly and set provider budgets/alerts. Tune capacity using measured peak load rather than average load.
- Add Redis for shared limits/cache/pub-sub only if multiple replicas or measured latency require it. Add a durable queue/worker for retryable external or slow work only when needed.
- Review dependency updates, vulnerability reports, access logs, retention, support workflow, and incident escalation.

**Exit gate:** stable pilot for an agreed observation period; service objectives and budget met; no unresolved high-risk security findings; support and recovery runbooks exercised.

### Phase 4 — Scale by evidence (after pilot)

- Autoscale stateless API instances on request concurrency, CPU, and latency with bounded maximum capacity and database-aware safeguards.
- Scale read-heavy discovery/status paths with query/index improvements and carefully invalidated caches; use read replicas only after measuring database read pressure.
- Move event processing to a queue/worker only when event volume or external integrations make synchronous work unreliable.
- Re-test multi-region, disaster recovery, or stronger availability only when contractual/user needs justify their cost and operational burden.

**Exit gate:** each scale component has a measured bottleneck, a cost owner, a rollback plan, and a success metric.

## Security acceptance checklist

- [ ] Production secrets are unique per environment, stored in a managed secret system, rotated, and absent from source and logs.
- [ ] TLS is enforced for clients, gateway ingress, application-to-database, and service-to-service traffic where applicable.
- [ ] Every protected route and WebSocket subscription validates authentication, role, active account, and resource ownership.
- [ ] Tests cover IDOR/cross-driver and cross-operator access, role escalation, expired/wrong token types, and inactive accounts.
- [ ] Gateway credentials are per device and revocable; signature validation includes freshness and replay prevention.
- [ ] Rate, payload, pagination, connection, and timeout limits are configured and monitored.
- [ ] Database access is private and least-privileged; encryption, backups, retention, and restore are verified.
- [ ] Logs and traces redact credentials and sensitive personal/location data; access to production telemetry is controlled.
- [ ] CI checks tests, dependency vulnerabilities, secrets, and migration safety; high-severity findings block release.
- [ ] Incident response, credential revocation, backup restore, and application rollback are documented and rehearsed.

## Performance and reliability objectives

Initial pilot targets (to be confirmed after baseline measurements):

- **REST latency:** p95 under 300 ms for application-only read/write endpoints at the agreed peak load; p99 under 1 second, excluding external provider latency.
- **Availability:** 99.5% monthly for pilot API endpoints, excluding agreed maintenance and third-party outages.
- **Live status:** p95 telemetry-to-dashboard propagation under 2 seconds when the gateway and client are connected.
- **Gateway ingestion:** p95 under 500 ms to acknowledge a valid status event; persist or durably queue events before acknowledging if loss is unacceptable.
- **Errors:** under 1% server-side errors at target load, with dependency errors separately classified.
- **Recovery:** agree on recovery time objective (RTO) and recovery point objective (RPO) before launch; prove them with restore exercises rather than assumptions.

Measure by endpoint and workload. If targets are missed, profile first, inspect database query plans and pool saturation, then optimize the bottleneck before scaling architecture.

## Cost model and guardrails

Illustrative monthly planning bands for a single-region, low-traffic pilot with moderate logs/storage. Actual provider, region, network egress, managed-service minimums, and redundancy materially change prices.

- **Development/staging:** approximately **$20–$100/month** when using minimal or shared resources and shutting down nonessential environments when idle.
- **Single-instance pilot:** approximately **$100–$350/month** for a small app service, managed PostgreSQL with backups, basic edge protection, and modest monitoring. This is a lower-resilience option and may have service downtime during an instance or database maintenance event.
- **More resilient pilot:** approximately **$300–$900+/month** for redundant app capacity, stronger managed database availability/backups, WAF, centralized monitoring, and optional cache/queue. Provider-specific baseline fees may exceed this range.

These are order-of-magnitude planning estimates, not cloud quotes. They exclude engineering time, map/geocoding, SMS/email, payment processing, taxes, and unusually high egress or log volume. Select an actual provider and region and replace them with a calculator-based estimate before launch.

Cost controls:

- Set monthly budgets, threshold alerts, and per-environment ownership before enabling production resources.
- Tag resources by environment/service/owner; review database storage, backups, logs, egress, and idle environments weekly during the pilot.
- Keep detailed logs only as long as needed; use retention tiers and redact/minimize personal data.
- Do not add Kubernetes, multiple databases, a service mesh, or microservices for the pilot without a measured requirement.
- Compare cost per 1,000 API requests and cost per active charging session monthly; investigate step changes.
- Preserve backups and security controls; reduce idle capacity and waste before weakening resilience.

## Risks and mitigations

- **Shared gateway credentials or leaked defaults:** unique device credentials, secret manager, rotation, replay defense, and alerting.
- **Authorization mistakes expose another tenant's data:** scoped queries, deny-by-default checks, adversarial cross-tenant tests, and audit events for sensitive operations.
- **SQLite or local storage becomes a production bottleneck/single point of failure:** move production to managed PostgreSQL and test migration/restore.
- **In-memory WebSocket/rate-limit state breaks across replicas:** use shared pub/sub or distributed limits when scaling out; test reconnect and duplicate delivery behavior.
- **Unbounded telemetry, connections, or logs inflate cost or cause outages:** apply quotas, rate/size limits, retention, cost alerts, and overload tests.
- **Premature infrastructure complexity consumes budget:** retain a modular monolith and introduce shared services only against measured bottlenecks.

## Ownership and review cadence

Assign named owners for application/security, infrastructure/cost, data/recovery, and pilot operations before Phase 1. Review the security checklist at every release, spend and SLOs weekly during the pilot, and revisit architecture quarterly or after a material change in traffic, data sensitivity, or external integrations.
