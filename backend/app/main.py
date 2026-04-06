from __future__ import annotations

import asyncio
import csv
import io
import json
import os
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from jose import JWTError, jwt
from passlib.context import CryptContext
from reportlab.pdfgen import canvas
import redis
from sqlalchemy import desc, func, select, text
from sqlalchemy.orm import Session

from .database import Base, SessionLocal, engine
from .models import Alarm, AlarmEvent, Device, EventLog, Measurement, Sensor, User
from .schemas import (
    AlarmCreate,
    AlarmEventOut,
    AlarmOut,
    AlarmUpdate,
    DeviceCreate,
    DeviceOut,
    DeviceUpdate,
    EventOut,
    LoginInput,
    MeasurementIn,
    MeasurementOut,
    SensorCreate,
    SensorOut,
    SensorUpdate,
    TokenOut,
    UserCreate,
    UserOut,
)

SECRET_KEY = os.getenv("JWT_SECRET", "dev-secret-change-me")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 12
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self.active_connections.discard(websocket)

    async def broadcast(self, payload: dict) -> None:
        message = json.dumps(payload, default=str)
        stale: list[WebSocket] = []
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                stale.append(connection)
        for connection in stale:
            self.disconnect(connection)


manager = ConnectionManager()
ALARM_STATE: dict[int, datetime] = {}


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def hash_password(password: str) -> str:
    return pwd_context.hash(password[:1024])


def verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify(password, hashed)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(UTC) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc


def get_current_user(token: str, db: Session) -> User:
    payload = decode_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = db.get(User, int(user_id))
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not active")
    return user


def require_role(user: User, allowed: set[str]):
    if user.role not in allowed:
        raise HTTPException(status_code=403, detail="Insufficient role")


def log_event(db: Session, event_type: str, description: str, user_id: int | None = None) -> None:
    db.add(EventLog(type=event_type, description=description, user_id=user_id))


def get_actor_from_header(authorization: str | None, db: Session) -> User | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    try:
        return get_current_user(token, db)
    except Exception:
        return None


def publish_control_event(payload: dict) -> None:
    try:
        client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        client.publish("rms:control", json.dumps(payload))
    except Exception:
        pass


def resolve_sensor(db: Session, payload: MeasurementIn) -> Sensor:
    if payload.sensor_id:
        sensor = db.get(Sensor, payload.sensor_id)
        if not sensor:
            raise HTTPException(status_code=404, detail="Sensor not found")
        return sensor
    if payload.device_name and payload.sensor_name:
        stmt = (
            select(Sensor)
            .join(Device, Device.id == Sensor.device_id)
            .where(Device.name == payload.device_name, Sensor.name == payload.sensor_name)
        )
        sensor = db.scalars(stmt).first()
        if not sensor:
            raise HTTPException(status_code=404, detail="Sensor not found by name")
        return sensor
    raise HTTPException(status_code=422, detail="Provide sensor_id or device_name+sensor_name")


async def evaluate_alarms(db: Session, sensor: Sensor, value: float, measurement_ts: datetime) -> list[dict]:
    alerts: list[dict] = []
    alarms = db.scalars(select(Alarm).where(Alarm.sensor_id == sensor.id, Alarm.enabled.is_(True))).all()
    for alarm in alarms:
        active_event = db.scalars(
            select(AlarmEvent).where(AlarmEvent.alarm_id == alarm.id, AlarmEvent.status == "ACTIVE")
        ).first()

        triggered = False
        message = ""
        if alarm.type == "high" and alarm.max_value is not None and value > alarm.max_value:
            triggered = True
            message = f"High threshold exceeded: {value} > {alarm.max_value}"
        elif alarm.type == "low" and alarm.min_value is not None and value < alarm.min_value:
            triggered = True
            message = f"Low threshold breached: {value} < {alarm.min_value}"

        if triggered:
            last = ALARM_STATE.get(alarm.id)
            now = datetime.now(UTC)
            if last and (now - last).total_seconds() < alarm.debounce_sec:
                continue
            ALARM_STATE[alarm.id] = now
            if not active_event:
                event = AlarmEvent(
                    alarm_id=alarm.id,
                    sensor_id=sensor.id,
                    start_time=measurement_ts,
                    value=value,
                    status="ACTIVE",
                    message=message,
                )
                db.add(event)
                db.flush()
                alert = {
                    "type": "alarm",
                    "event": "triggered",
                    "alarm_id": alarm.id,
                    "sensor_id": sensor.id,
                    "severity": alarm.severity,
                    "message": message,
                    "start_time": event.start_time.isoformat(),
                }
                alerts.append(alert)
                log_event(db, "alarm_triggered", message)
        else:
            if active_event:
                active_event.status = "RESOLVED"
                active_event.end_time = measurement_ts
                alert = {
                    "type": "alarm",
                    "event": "resolved",
                    "alarm_id": alarm.id,
                    "sensor_id": sensor.id,
                    "severity": alarm.severity,
                    "message": f"Alarm resolved for sensor {sensor.name}",
                    "end_time": measurement_ts.isoformat(),
                }
                alerts.append(alert)
                log_event(db, "alarm_resolved", alert["message"])
    return alerts


def ensure_default_admin(db: Session) -> None:
    exists = db.scalars(select(User).where(User.email == "admin@rms.local")).first()
    if exists:
        return
    admin = User(email="admin@rms.local", password_hash=hash_password("admin123"), role="admin")
    db.add(admin)
    db.add(EventLog(type="system", description="Default admin user created", user_id=None))
    db.commit()




def sync_db_to_json(db: Session) -> None:
    path = os.getenv("DEVICES_CONFIG_PATH", "/app/config/devices.json")
    devices = db.scalars(select(Device).order_by(Device.id)).all()
    payload = {"devices": []}
    for d in devices:
        sensors = db.scalars(select(Sensor).where(Sensor.device_id == d.id).order_by(Sensor.id)).all()
        payload["devices"].append({
            "device_name": d.name,
            "protocol": d.protocol,
            "port": d.port,
            "slave_id": d.slave_id,
            "poll_interval": d.poll_interval,
            "sensors": [
                {
                    "name": s.name,
                    "unit": s.unit,
                    "data_type": s.data_type,
                    "address": s.register_address,
                    "scale": s.scale,
                    "base": 0,
                    "noise": 1,
                    "min": -100,
                    "max": 100,
                }
                for s in sensors
            ],
        })
    try:
        Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception:
        pass
def sync_devices_from_json(db: Session) -> None:
    path = os.getenv("DEVICES_CONFIG_PATH", "/app/config/devices.json")
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    for dev in data.get("devices", []):
        device = db.scalars(select(Device).where(Device.name == dev["device_name"])).first()
        if not device:
            device = Device(
                name=dev["device_name"],
                protocol=dev.get("protocol", "modbus_rtu"),
                port=dev.get("port", "RS485_1"),
                slave_id=int(dev.get("slave_id", 1)),
                poll_interval=int(dev.get("poll_interval", 5)),
                status="ONLINE",
            )
            db.add(device)
            db.flush()
        for sensor in dev.get("sensors", []):
            exists = db.scalars(
                select(Sensor).where(Sensor.device_id == device.id, Sensor.name == sensor["name"])
            ).first()
            if not exists:
                db.add(
                    Sensor(
                        device_id=device.id,
                        name=sensor["name"],
                        unit=sensor.get("unit", ""),
                        data_type=sensor.get("data_type", "float32"),
                        register_address=sensor.get("address"),
                        scale=float(sensor.get("scale", 1.0)),
                        is_active=True,
                    )
                )
    db.commit()


async def monitor_timeouts() -> None:
    while True:
        await asyncio.sleep(5)
        with SessionLocal() as db:
            now = datetime.now(UTC)
            alarms = db.scalars(select(Alarm).where(Alarm.enabled.is_(True), Alarm.type.in_(["no_data_timeout", "device_offline"]))).all()
            emitted = []
            for alarm in alarms:
                sensor = db.get(Sensor, alarm.sensor_id)
                if not sensor:
                    continue
                active = db.scalars(select(AlarmEvent).where(AlarmEvent.alarm_id == alarm.id, AlarmEvent.status == "ACTIVE")).first()
                if alarm.type == "no_data_timeout":
                    ref = sensor.last_seen
                    overdue = (ref is None) or ((now - ref).total_seconds() > alarm.timeout_sec)
                    msg = f"No data timeout for sensor {sensor.name}"
                else:
                    ref = sensor.device.last_seen
                    overdue = (ref is None) or ((now - ref).total_seconds() > alarm.timeout_sec)
                    msg = f"Device offline for {sensor.device.name}"

                if overdue and not active:
                    ev = AlarmEvent(alarm_id=alarm.id, sensor_id=sensor.id, start_time=now, status="ACTIVE", message=msg)
                    db.add(ev)
                    log_event(db, "alarm_triggered", msg)
                    emitted.append({"type":"alarm","event":"triggered","alarm_id":alarm.id,"sensor_id":sensor.id,"severity":alarm.severity,"message":msg,"start_time":now.isoformat()})
                if (not overdue) and active:
                    active.status = "RESOLVED"
                    active.end_time = now
                    resolved_msg = f"Timeout alarm resolved for sensor {sensor.name}"
                    log_event(db, "alarm_resolved", resolved_msg)
                    emitted.append({"type":"alarm","event":"resolved","alarm_id":alarm.id,"sensor_id":sensor.id,"severity":alarm.severity,"message":resolved_msg,"end_time":now.isoformat()})
            db.commit()
        for item in emitted:
            await manager.broadcast(item)


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        try:
            db.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb;"))
            db.execute(text("SELECT create_hypertable('measurements', 'timestamp', if_not_exists => TRUE, migrate_data => TRUE);"))
            db.commit()
        except Exception:
            db.rollback()
        sync_devices_from_json(db)
        ensure_default_admin(db)
    monitor_task = asyncio.create_task(monitor_timeouts())
    yield
    monitor_task.cancel()


app = FastAPI(title="RMS Backend", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    devices = db.scalar(select(func.count(Device.id)))
    sensors = db.scalar(select(func.count(Sensor.id)))
    return {"status": "ok", "devices": devices, "sensors": sensors}


@app.post("/auth/login", response_model=TokenOut)
def login(payload: LoginInput, db: Session = Depends(get_db)):
    user = db.scalars(select(User).where(User.email == payload.email)).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token({"sub": str(user.id), "role": user.role})
    return TokenOut(access_token=token)


@app.post("/users", response_model=UserOut)
def create_user(payload: UserCreate, db: Session = Depends(get_db), token: str = ""):
    if token:
        actor = get_current_user(token, db)
        require_role(actor, {"admin"})
    user = User(email=payload.email, password_hash=hash_password(payload.password), role=payload.role)
    db.add(user)
    log_event(db, "user_created", f"User {payload.email} created")
    db.commit()
    db.refresh(user)
    return user


@app.get("/devices", response_model=list[DeviceOut])
def get_devices(db: Session = Depends(get_db)):
    return list(db.scalars(select(Device).order_by(Device.id)).all())


@app.post("/devices", response_model=DeviceOut)
def create_device(payload: DeviceCreate, db: Session = Depends(get_db)):
    device = Device(**payload.model_dump(), status="ONLINE")
    db.add(device)
    log_event(db, "device_created", f"Device {payload.name} created")
    db.commit()
    sync_db_to_json(db)
    db.refresh(device)
    return device


@app.put("/devices/{device_id}", response_model=DeviceOut)
def update_device(device_id: int, payload: DeviceUpdate, db: Session = Depends(get_db)):
    device = db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    for key, value in payload.model_dump(exclude_none=True).items():
        setattr(device, key, value)
    log_event(db, "device_updated", f"Device {device.name} updated")
    db.commit()
    sync_db_to_json(db)
    db.refresh(device)
    return device


@app.delete("/devices/{device_id}")
def delete_device(device_id: int, db: Session = Depends(get_db)):
    device = db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    name = device.name
    db.delete(device)
    log_event(db, "device_deleted", f"Device {name} deleted")
    db.commit()
    sync_db_to_json(db)
    return {"deleted": True}


@app.get("/devices/{device_id}/sensors", response_model=list[SensorOut])
def get_device_sensors(device_id: int, db: Session = Depends(get_db)):
    return list(db.scalars(select(Sensor).where(Sensor.device_id == device_id).order_by(Sensor.id)).all())


@app.get("/sensors", response_model=list[SensorOut])
def get_sensors(device_id: int | None = None, db: Session = Depends(get_db)):
    stmt = select(Sensor).order_by(Sensor.id)
    if device_id:
        stmt = stmt.where(Sensor.device_id == device_id)
    return list(db.scalars(stmt).all())


@app.post("/sensors", response_model=SensorOut)
def create_sensor(payload: SensorCreate, db: Session = Depends(get_db)):
    sensor = Sensor(**payload.model_dump())
    db.add(sensor)
    log_event(db, "sensor_created", f"Sensor {payload.name} created")
    db.commit()
    sync_db_to_json(db)
    db.refresh(sensor)
    return sensor


@app.put("/sensors/{sensor_id}", response_model=SensorOut)
def update_sensor(sensor_id: int, payload: SensorUpdate, db: Session = Depends(get_db)):
    sensor = db.get(Sensor, sensor_id)
    if not sensor:
        raise HTTPException(status_code=404, detail="Sensor not found")
    for key, value in payload.model_dump(exclude_none=True).items():
        setattr(sensor, key, value)
    log_event(db, "sensor_updated", f"Sensor {sensor.name} updated")
    db.commit()
    sync_db_to_json(db)
    db.refresh(sensor)
    return sensor


@app.delete("/sensors/{sensor_id}")
def delete_sensor(sensor_id: int, db: Session = Depends(get_db)):
    sensor = db.get(Sensor, sensor_id)
    if not sensor:
        raise HTTPException(status_code=404, detail="Sensor not found")
    name = sensor.name
    db.delete(sensor)
    log_event(db, "sensor_deleted", f"Sensor {name} deleted")
    db.commit()
    sync_db_to_json(db)
    return {"deleted": True}


@app.post("/alarms", response_model=AlarmOut)
def create_alarm(payload: AlarmCreate, db: Session = Depends(get_db)):
    alarm = Alarm(**payload.model_dump())
    db.add(alarm)
    log_event(db, "alarm_config_created", f"Alarm {payload.type} for sensor {payload.sensor_id}")
    db.commit()
    db.refresh(alarm)
    return alarm


@app.get("/alarms", response_model=list[AlarmOut])
def list_alarms(db: Session = Depends(get_db), sensor_id: int | None = None):
    stmt = select(Alarm).order_by(Alarm.id)
    if sensor_id:
        stmt = stmt.where(Alarm.sensor_id == sensor_id)
    return list(db.scalars(stmt).all())


@app.put("/alarms/{alarm_id}", response_model=AlarmOut)
def update_alarm(alarm_id: int, payload: AlarmUpdate, db: Session = Depends(get_db)):
    alarm = db.get(Alarm, alarm_id)
    if not alarm:
        raise HTTPException(status_code=404, detail="Alarm not found")
    for key, value in payload.model_dump(exclude_none=True).items():
        setattr(alarm, key, value)
    log_event(db, "alarm_config_updated", f"Alarm {alarm_id} updated")
    db.commit()
    db.refresh(alarm)
    return alarm


@app.get("/alarms/events", response_model=list[AlarmEventOut])
def alarm_events(active_only: bool = False, db: Session = Depends(get_db)):
    stmt = select(AlarmEvent).order_by(desc(AlarmEvent.start_time)).limit(1000)
    if active_only:
        stmt = stmt.where(AlarmEvent.status == "ACTIVE")
    return list(db.scalars(stmt).all())


async def ingest_measurements(rows: list[MeasurementIn], db: Session) -> list[dict]:
    responses: list[dict] = []
    alerts_all: list[dict] = []
    now = datetime.now(UTC)

    for row in rows:
        sensor = resolve_sensor(db, row)
        ts = row.timestamp or now
        measurement = Measurement(sensor_id=sensor.id, value=row.value, quality=row.quality, timestamp=ts)
        db.add(measurement)
        sensor.last_seen = ts
        sensor.device.last_seen = ts
        sensor.device.status = "ONLINE"
        alerts = await evaluate_alarms(db, sensor, row.value, ts)
        alerts_all.extend(alerts)
        responses.append({"sensor_id": sensor.id, "value": row.value, "quality": row.quality, "timestamp": ts})

    db.commit()
    for item in responses:
        await manager.broadcast({"type": "measurement", **item})
    for alert in alerts_all:
        await manager.broadcast(alert)
    return responses


@app.post("/data", response_model=MeasurementOut)
async def post_data(item: MeasurementIn, db: Session = Depends(get_db)):
    res = await ingest_measurements([item], db)
    last = res[-1]
    row = db.scalars(
        select(Measurement)
        .where(Measurement.sensor_id == last["sensor_id"])
        .order_by(desc(Measurement.id))
        .limit(1)
    ).first()
    return row


@app.post("/data/batch")
async def post_data_batch(items: list[MeasurementIn], db: Session = Depends(get_db)):
    if not items:
        return {"inserted": 0}
    rows = await ingest_measurements(items, db)
    return {"inserted": len(rows)}


@app.get("/data")
def get_data(
    limit: int = 200,
    sensor_ids: str | None = None,
    range: str = "10m",
    db: Session = Depends(get_db),
):
    limit = max(1, min(limit, 5000))
    stmt = select(Measurement).order_by(desc(Measurement.timestamp)).limit(limit)
    if sensor_ids:
        ids = [int(x) for x in sensor_ids.split(",") if x.strip().isdigit()]
        stmt = stmt.where(Measurement.sensor_id.in_(ids))

    if range == "1h":
        stmt = stmt.where(Measurement.timestamp >= datetime.now(UTC) - timedelta(hours=1))
    elif range == "24h":
        stmt = stmt.where(Measurement.timestamp >= datetime.now(UTC) - timedelta(hours=24))
    else:
        stmt = stmt.where(Measurement.timestamp >= datetime.now(UTC) - timedelta(minutes=10))

    rows = list(db.scalars(stmt).all())[::-1]
    return [
        {
            "id": r.id,
            "timestamp": r.timestamp,
            "sensor_id": r.sensor_id,
            "value": r.value,
            "quality": r.quality,
        }
        for r in rows
    ]


@app.get("/events", response_model=list[EventOut])
def get_events(limit: int = 200, db: Session = Depends(get_db)):
    stmt = select(EventLog).order_by(desc(EventLog.timestamp)).limit(max(1, min(limit, 2000)))
    return list(db.scalars(stmt).all())


@app.get("/reports/csv")
def export_csv(db: Session = Depends(get_db), hours: int = 1):
    cutoff = datetime.now(UTC) - timedelta(hours=max(1, min(hours, 168)))
    stmt = (
        select(Measurement.timestamp, Sensor.name, Device.name, Measurement.value, Measurement.quality)
        .join(Sensor, Sensor.id == Measurement.sensor_id)
        .join(Device, Device.id == Sensor.device_id)
        .where(Measurement.timestamp >= cutoff)
        .order_by(Measurement.timestamp.asc())
    )
    rows = db.execute(stmt).all()
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["timestamp", "device", "sensor", "value", "quality"])
    writer.writerows([[r[0], r[2], r[1], r[3], r[4]] for r in rows])
    return Response(
        content=stream.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=rms_report.csv"},
    )


@app.get("/reports/pdf")
def export_pdf(db: Session = Depends(get_db), hours: int = 1):
    cutoff = datetime.now(UTC) - timedelta(hours=max(1, min(hours, 168)))
    stmt = (
        select(Measurement.timestamp, Sensor.name, Device.name, Measurement.value)
        .join(Sensor, Sensor.id == Measurement.sensor_id)
        .join(Device, Device.id == Sensor.device_id)
        .where(Measurement.timestamp >= cutoff)
        .order_by(Measurement.timestamp.asc())
        .limit(300)
    )
    rows = db.execute(stmt).all()

    buf = io.BytesIO()
    p = canvas.Canvas(buf)
    p.setFont("Helvetica", 10)
    p.drawString(40, 800, "RMS Temperature Report")
    y = 780
    for ts, sensor, device, value in rows:
        p.drawString(40, y, f"{ts} | {device}:{sensor} | {value}")
        y -= 14
        if y < 40:
            p.showPage()
            p.setFont("Helvetica", 10)
            y = 800
    p.save()
    return Response(
        content=buf.getvalue(),
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=rms_report.pdf"},
    )




@app.post("/alarms/events/{event_id}/ack")
def acknowledge_alarm(event_id: int, db: Session = Depends(get_db)):
    event = db.get(AlarmEvent, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Alarm event not found")
    if event.status == "ACTIVE":
        event.status = "ACKED"
    log_event(db, "alarm_ack", f"Alarm event {event_id} acknowledged")
    db.commit()
    return {"acknowledged": True}


@app.get("/dashboard/summary")
def dashboard_summary(db: Session = Depends(get_db)):
    active_alarms = db.scalar(select(func.count(AlarmEvent.id)).where(AlarmEvent.status == "ACTIVE"))
    devices_total = db.scalar(select(func.count(Device.id)))
    sensors_total = db.scalar(select(func.count(Sensor.id)))
    online_devices = db.scalar(select(func.count(Device.id)).where(Device.status == "ONLINE"))
    latest_stmt = (
        select(Sensor.id, Sensor.name, Device.name, Measurement.value, Measurement.timestamp, Measurement.quality)
        .join(Device, Device.id == Sensor.device_id)
        .join(Measurement, Measurement.sensor_id == Sensor.id)
        .order_by(Measurement.timestamp.desc())
        .limit(20)
    )
    latest = [
        {
            "sensor_id": r[0],
            "sensor_name": r[1],
            "device_name": r[2],
            "value": r[3],
            "timestamp": r[4],
            "quality": r[5],
        }
        for r in db.execute(latest_stmt).all()
    ]
    return {
        "active_alarms": active_alarms or 0,
        "devices_total": devices_total or 0,
        "sensors_total": sensors_total or 0,
        "online_devices": online_devices or 0,
        "latest": latest,
    }




@app.get("/data/latest")
def data_latest(device_id: int | None = None, db: Session = Depends(get_db)):
    stmt = (
        select(Measurement.id, Measurement.sensor_id, Measurement.value, Measurement.quality, Measurement.timestamp, Sensor.name, Device.id, Device.name)
        .join(Sensor, Sensor.id == Measurement.sensor_id)
        .join(Device, Device.id == Sensor.device_id)
        .order_by(Measurement.timestamp.desc())
        .limit(5000)
    )
    rows = db.execute(stmt).all()
    latest = {}
    for row in rows:
        d_id = row[6]
        if device_id and d_id != device_id:
            continue
        key = row[1]
        if key not in latest:
            latest[key] = {
                "measurement_id": row[0],
                "sensor_id": row[1],
                "value": row[2],
                "quality": row[3],
                "timestamp": row[4],
                "sensor_name": row[5],
                "device_id": row[6],
                "device_name": row[7],
            }
    return list(latest.values())


@app.get("/data/history")
def data_history(
    device_id: int | None = None,
    sensor_id: int | None = None,
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
    agg: str = "raw",
    db: Session = Depends(get_db),
):
    stmt = (
        select(Measurement.timestamp, Measurement.sensor_id, Measurement.value, Measurement.quality)
        .join(Sensor, Sensor.id == Measurement.sensor_id)
        .join(Device, Device.id == Sensor.device_id)
        .order_by(Measurement.timestamp.asc())
        .limit(20000)
    )
    if device_id:
        stmt = stmt.where(Device.id == device_id)
    if sensor_id:
        stmt = stmt.where(Measurement.sensor_id == sensor_id)
    if from_ts:
        stmt = stmt.where(Measurement.timestamp >= from_ts)
    if to_ts:
        stmt = stmt.where(Measurement.timestamp <= to_ts)
    rows = db.execute(stmt).all()

    if agg == "raw":
        return [{"timestamp": r[0], "sensor_id": r[1], "value": r[2], "quality": r[3]} for r in rows]

    bucket = {"1m": 60, "5m": 300, "1h": 3600}.get(agg, 60)
    out = {}
    for ts, sid, val, q in rows:
        epoch = int(ts.timestamp())
        group_ts = datetime.fromtimestamp(epoch - (epoch % bucket), tz=UTC)
        key = (sid, group_ts)
        out.setdefault(key, []).append(val)
    return [{"sensor_id": k[0], "timestamp": k[1], "avg_value": sum(v)/len(v)} for k, v in sorted(out.items(), key=lambda x: x[0][1])]


@app.post("/alarms/ack")
def ack_alarm(payload: dict, db: Session = Depends(get_db)):
    event_id = payload.get("event_id")
    if not event_id:
        raise HTTPException(status_code=422, detail="event_id required")
    event = db.get(AlarmEvent, int(event_id))
    if not event:
        raise HTTPException(status_code=404, detail="Alarm event not found")
    event.status = "ACKED"
    log_event(db, "alarm_ack", f"Alarm event {event_id} acknowledged")
    db.commit()
    return {"acknowledged": True}


@app.post("/control")
def control_device(payload: dict, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    actor = get_actor_from_header(authorization, db)
    if not actor:
        raise HTTPException(status_code=401, detail="Authorization required")
    require_role(actor, {"admin", "operator"})

    device_id = payload.get("device_id")
    command = payload.get("command")
    value = payload.get("value")
    if not device_id or not command:
        raise HTTPException(status_code=422, detail="device_id and command required")

    event_payload = {
        "device_id": device_id,
        "command": command,
        "value": value,
        "issued_by": actor.email,
        "issued_at": datetime.now(UTC).isoformat(),
    }
    publish_control_event(event_payload)
    log_event(db, "control_command", json.dumps(event_payload), actor.id)
    db.commit()
    return {"queued": True, **event_payload}


@app.get("/users", response_model=list[UserOut])
def list_users(authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    actor = get_actor_from_header(authorization, db)
    if not actor:
        raise HTTPException(status_code=401, detail="Authorization required")
    require_role(actor, {"admin"})
    return list(db.scalars(select(User).order_by(User.id)).all())


@app.get("/backup/export")
def backup_export(db: Session = Depends(get_db)):
    devices = db.execute(select(Device.id, Device.name, Device.protocol, Device.port, Device.status)).all()
    sensors = db.execute(select(Sensor.id, Sensor.device_id, Sensor.name, Sensor.unit, Sensor.data_type)).all()
    alarms = db.execute(select(Alarm.id, Alarm.sensor_id, Alarm.type, Alarm.severity, Alarm.enabled)).all()
    measurements = db.execute(select(Measurement.timestamp, Measurement.sensor_id, Measurement.value, Measurement.quality).order_by(Measurement.timestamp.desc()).limit(5000)).all()
    return {
        "exported_at": datetime.now(UTC),
        "devices": [dict(id=r[0], name=r[1], protocol=r[2], port=r[3], status=r[4]) for r in devices],
        "sensors": [dict(id=r[0], device_id=r[1], name=r[2], unit=r[3], data_type=r[4]) for r in sensors],
        "alarms": [dict(id=r[0], sensor_id=r[1], type=r[2], severity=r[3], enabled=r[4]) for r in alarms],
        "measurements": [dict(timestamp=r[0], sensor_id=r[1], value=r[2], quality=r[3]) for r in measurements],
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)
