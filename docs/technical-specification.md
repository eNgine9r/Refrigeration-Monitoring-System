# Refrigeration Monitoring System (RMS) — Technical Specification

## 1. Scope and goals
RMS is a web-based monitoring platform for refrigeration laboratory testing, designed as a scalable local-server alternative to XWEB Pro and aligned with ISO 23953 requirements.

Primary goals:
- Poll 150+ sensors (target scalability: 200+).
- Keep full acquisition cycle at or below 20 seconds per sensor.
- Ensure append-only, auditable, non-modifiable historical data.
- Support real-time supervision through a browser dashboard.
- Support multi-RS485 acquisition architecture.

## 2. High-level architecture

```text
[Devices: Modbus RTU/TCP]
           ↓
[Collector Service: multi-RS485 workers]
           ↓
[Backend API + Alarm Engine]
           ↓
[PostgreSQL + TimescaleDB]
           ↓
[WebSocket Gateway]
           ↓
[Frontend Dashboard]
```

## 3. Functional requirements

### 3.1 Device abstraction layer (mandatory)
- No hardcoded per-device logic in source code.
- Devices and register maps are defined via JSON profiles.
- New devices are onboarded by configuration only.

Supported protocols:
- `modbus_rtu`
- `modbus_tcp`

Supported register data types:
- `int16`
- `uint16`
- `float32`
- `bool`

### 3.2 Collector service
- Minimum 4 parallel RS485 workers.
- Maximum design target: 50 devices per RS485 bus.
- Batch reads of contiguous registers whenever possible.
- Retries: 3 attempts.
- Per-attempt timeout: 1 second.
- Offline marking when retries fail.
- Non-blocking: one failing device must not stop worker loop.
- Local persistence buffer when backend is unavailable.

### 3.3 Alarm engine
Alarm types:
- High threshold.
- Low threshold.
- No data timeout.
- Device offline.

Rules:
- Trigger when value exceeds configured limits.
- Auto-recover when values return to normal.
- Debounce window: 30–60 seconds.
- Persist complete alarm history.
- Push updates via WebSocket.

### 3.4 Frontend and reporting
Required pages:
- Dashboard.
- Device detail page.
- Alarms page.
- Reports page (PDF/CSV export).

Charting features:
- Real-time updates.
- Multi-sensor overlay.
- Selectable time windows (minutes/hours/days).
- Zoom and pan.

## 4. Data model

Core tables:
- `devices`
- `sensors`
- `measurements` (Timescale hypertable)
- `alarms`
- `alarm_events`
- `events` (audit)
- `users`

Data governance requirements:
- Append-only measurement history.
- Full audit trail for user/system actions.
- No historical data edits.

## 5. Security and access control
- JWT authentication.
- RBAC roles: Admin, Operator, Viewer.
- HTTPS support for deployment.
- Login and security event logging.

## 6. Deployment
Target runtime:
- Local Linux/Windows server.

Containerized services:
- `collector`
- `backend`
- `database`
- `frontend`

Access targets:
- `http://localhost:3000`
- `http://<local-ip>:3000`

## 7. Constraints and non-negotiables
The platform must **not**:
- Use hardcoded device logic.
- Block due to single-device communication failure.
- Lose measurement data during transient outages.
- Allow editing historical data.

## 8. Delivery roadmap
- **Phase 1 (MVP):** single RS485, basic collector, basic UI.
- **Phase 2:** multi-RS485 workers, real-time charts, config-driven devices.
- **Phase 3:** alarms, RBAC, ISO audit logging.
- **Phase 4:** reporting, optimization, scaling hardening.
