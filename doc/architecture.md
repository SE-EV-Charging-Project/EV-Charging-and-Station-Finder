# ChargeSlot Architecture

This diagram reflects the application components present in `chargeslot/backend`. Driver, operator, and administrator clients consume the API; no specific frontend implementation is assumed.

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
