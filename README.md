# Refrigeration Monitoring System (RMS)

## Швидкий старт

### 1) Вимоги
- Docker
- Docker Compose (plugin `docker compose` або legacy `docker-compose`)

### 2) Запуск всього стенду
```bash
docker compose up --build
```

### 3) Доступ до сервісів
- UI: http://localhost:3000
- API: http://localhost:8000
- Health: http://localhost:8000/health

## Склад системи
- `db`: TimescaleDB/PostgreSQL
- `backend`: FastAPI (REST + WebSocket + Alarm Engine + Reports + Auth)
- `collector`: multi-port simulated collector (Modbus-ready architecture)
- `frontend`: React + Vite SPA (build) через nginx
- `redis`: pub/sub для команд керування та розширень

## Структура
- `backend/app/main.py` — API, WebSocket, alarm engine, reports, auth
- `backend/app/models.py` — повна схема БД
- `collector/app/main.py` — воркери RS485, retry/timeout, batch ingest, buffering
- `collector/config/devices.json` — конфігурація пристроїв/сенсорів
- `frontend/index.html` — Dashboard/Devices/Alarms/Reports

## Перший логін
Backend створює дефолтного адміна при старті:
- email: `admin@rms.local`
- password: `admin123`

> Рекомендується змінити пароль і `JWT_SECRET` в `docker-compose.yml`.

## Основні API

### Auth
- `POST /auth/login`

Приклад:
```bash
curl -X POST http://localhost:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@rms.local","password":"admin123"}'
```

### Devices CRUD
- `GET /devices`
- `POST /devices`
- `PUT /devices/{id}`
- `DELETE /devices/{id}`

### Sensors CRUD
- `GET /sensors`
- `POST /sensors`
- `PUT /sensors/{id}`
- `DELETE /sensors/{id}`

### Alarms
- `GET /alarms`
- `POST /alarms`
- `PUT /alarms/{id}`
- `GET /alarms/events`
- `GET /alarms/events?active_only=true`

### Data Ingest
- `POST /data`
- `POST /data/batch`
- `GET /data?limit=2000&sensor_ids=1,2,3&range=10m|1h|24h`
- `GET /data/latest`
- `GET /data/history?device_id=&sensor_id=&from_ts=&to_ts=&agg=raw|1m|5m|1h`

### Reports
- `GET /reports/csv?hours=24`
- `GET /reports/pdf?hours=24`

### Control
- `POST /control` (Bearer token, roles: admin/operator)

### Backup
- `GET /backup/export`

### Audit
- `GET /events?limit=300`

### WebSocket
- `WS /ws`

Повідомлення:
- measurement: `{ "type":"measurement", "sensor_id":..., "value":..., "quality":"OK|ERROR|OFFLINE", "timestamp":... }`
- alarm: `{ "type":"alarm", "event":"triggered|resolved", ... }`

## Конфігурація collector

Файл: `collector/config/devices.json`

Поля пристрою:
- `device_name`
- `protocol`
- `port`
- `slave_id`
- `poll_interval` (2..5 сек)
- `sensors[]`

Поля сенсора:
- `name`
- `base`, `noise`, `min`, `max` (для симуляції)
- `unit`, `data_type`

Після зміни конфіга:
```bash
docker compose restart collector backend
```

## Перевірка роботи

### 1) Перевірка health
```bash
curl http://localhost:8000/health
```

### 2) Перевірка сенсорів
```bash
curl http://localhost:8000/sensors
```

### 3) Перевірка даних
```bash
curl 'http://localhost:8000/data?limit=50'
```

### 4) Активні аварії
```bash
curl 'http://localhost:8000/alarms/events?active_only=true'
```

### 5) Експорт CSV
```bash
curl -OJ 'http://localhost:8000/reports/csv?hours=24'
```

## Зупинка
```bash
docker compose down
```

Видалити томи (повний reset):
```bash
docker compose down -v
```


## UI/UX
- Light/Dark theme toggle (persisted in localStorage)
- Responsive desktop/mobile layout with bottom nav on mobile
- Real-time dashboard cards/charts + alarm pulse states
- Floor plan map page with draggable device markers
