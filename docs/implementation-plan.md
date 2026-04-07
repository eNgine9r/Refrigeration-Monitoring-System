# RMS Implementation Plan

## A. Technology stack (recommended)
- **Collector:** Python 3.12 + `pymodbus` + `asyncio`
- **Backend API:** FastAPI + SQLAlchemy + Alembic
- **Realtime:** WebSocket endpoint in backend (or Redis pub/sub + gateway)
- **Database:** PostgreSQL 16 + TimescaleDB
- **Frontend:** Next.js (App Router) + TypeScript + Chart.js/Recharts
- **Auth:** JWT (access + refresh), bcrypt/argon2 password hashing
- **Observability:** Prometheus metrics + structured JSON logging

## B. Delivery increments

### Increment 1 — foundation
- Repository scaffolding and service boundaries.
- Database migrations for required tables.
- Basic authentication with role model.
- Collector simulator for test devices.

### Increment 2 — acquisition core
- Device profile loader + JSON Schema validation.
- Multi-worker bus scheduler.
- Register batching and decode pipeline.
- Buffered forwarding to backend.

### Increment 3 — realtime and alarms
- Measurement ingest API with batch writes.
- WebSocket broadcast channels.
- Alarm rule evaluation with debounce and recovery.
- Alarm event history endpoints.

### Increment 4 — frontend and reporting
- Dashboard/device/alarm/report pages.
- Real-time chart streaming.
- Historical query filtering and exports.

### Increment 5 — compliance hardening
- Append-only enforcement on measurements.
- Immutable audit event stream.
- NTP drift checks and missing-interval detection.

## C. Acceptance criteria
- 150+ sensors sustained with ≤20 second full polling cycle.
- Offline device handling does not block other devices.
- Buffered points are replayed after backend outage.
- Alarm transitions are persisted and pushed in real-time.
- Historical measurements cannot be modified by API users.
