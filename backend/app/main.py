from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from .database import Base, SessionLocal, engine
from .models import Measurement
from .schemas import MeasurementIn, MeasurementOut


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self.active_connections.discard(websocket)

    async def broadcast(self, payload: dict) -> None:
        dead_connections: list[WebSocket] = []
        for connection in self.active_connections:
            try:
                await connection.send_text(json.dumps(payload))
            except Exception:
                dead_connections.append(connection)
        for connection in dead_connections:
            self.disconnect(connection)


manager = ConnectionManager()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="RMS Backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/data", response_model=list[MeasurementOut])
def get_data(limit: int = 200, db: Session = Depends(get_db)):
    limit = max(1, min(limit, 5000))
    stmt = select(Measurement).order_by(desc(Measurement.timestamp)).limit(limit)
    return list(db.scalars(stmt).all())[::-1]


@app.post("/data", response_model=MeasurementOut)
async def post_data(item: MeasurementIn, db: Session = Depends(get_db)):
    row = Measurement(
        timestamp=item.timestamp or datetime.utcnow(),
        device_name=item.device_name,
        sensor_name=item.sensor_name,
        value=item.value,
        quality=item.quality,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    payload = MeasurementOut.model_validate(row).model_dump(mode="json")
    await manager.broadcast(payload)
    return row


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
