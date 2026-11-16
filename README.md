# ChargeSlot

ChargeSlot is an electric-vehicle charging station finder and reservation platform. This repository currently contains the Python backend in [`chargeslot/backend`](chargeslot/backend); the backend provides APIs for drivers, station operators, and administrators.

## Features

- Authentication, account management, and role-based access for drivers, operators, and administrators
- Vehicle profiles and battery state-of-charge tracking
- Station onboarding, moderation, discovery, and charger/connector status
- Booking management and battery-aware energy and range calculations
- Maintenance windows, station reviews, and favourites
- Real-time dashboard updates over WebSockets and charger status updates through the OCPP gateway

See the [backend README](chargeslot/backend/README.md) for the battery-level API details.

## Architecture and UML

- [Architecture diagram](doc/architecture.md) — application components and request/data flows
- [UML class diagram](doc/uml.md) — core domain entities and their relationships
- [Delivery and production-readiness plan (PDF)](doc/chargeslot-delivery-plan.pdf) — phased security, performance, reliability, and cost plan
- [Plan source](doc/chargeslot-delivery-plan.md) — accessible and editable Markdown version

Both diagrams use Mermaid and render in GitHub and compatible Markdown viewers.

## Technology

- Python and FastAPI
- SQLAlchemy ORM and Alembic migrations
- SQLite by default; the database URL can be configured through the environment
- Pytest for backend tests

## Run locally

From the repository root, create and activate a virtual environment, then install the backend dependencies:

```powershell
cd chargeslot\backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Before using the service beyond local development, set a private `SECRET_KEY` in `.env`. Configure `DATABASE_URL` there as needed; the default is a local SQLite database.

Apply database migrations and start the API:

```powershell
alembic upgrade head
uvicorn app.main:app --reload
```

- Health check: <http://127.0.0.1:8000/health>
- Interactive API documentation: <http://127.0.0.1:8000/api/v1/docs>

Run the backend tests from `chargeslot\backend`:

```powershell
python -m pytest
```

## Configuration

Backend settings are read from environment variables and, when present, `chargeslot/backend/.env`. See [`chargeslot/backend/.env.example`](chargeslot/backend/.env.example) for the development configuration template. Do not use the example secret values in a deployed environment or commit real credentials.
