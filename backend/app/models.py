from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from .database import Base


class Device(Base):
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False, unique=True, index=True)
    protocol = Column(String(30), nullable=False)
    port = Column(String(50), nullable=False, index=True)
    slave_id = Column(Integer, nullable=False)
    poll_interval = Column(Integer, nullable=False, default=5)
    status = Column(String(20), nullable=False, default="ONLINE")
    last_seen = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    sensors = relationship("Sensor", back_populates="device", cascade="all,delete")


class Sensor(Base):
    __tablename__ = "sensors"
    __table_args__ = (UniqueConstraint("device_id", "name", name="uq_sensor_per_device"),)

    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    unit = Column(String(20), nullable=False, default="")
    data_type = Column(String(20), nullable=False, default="float32")
    register_address = Column(Integer, nullable=True)
    scale = Column(Float, nullable=False, default=1.0)
    is_active = Column(Boolean, nullable=False, default=True)
    last_seen = Column(DateTime(timezone=True), nullable=True)

    device = relationship("Device", back_populates="sensors")


class Measurement(Base):
    __tablename__ = "measurements"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    sensor_id = Column(Integer, ForeignKey("sensors.id", ondelete="CASCADE"), nullable=False, index=True)
    value = Column(Float, nullable=False)
    quality = Column(String(20), nullable=False, default="OK")


class Alarm(Base):
    __tablename__ = "alarms"

    id = Column(Integer, primary_key=True)
    sensor_id = Column(Integer, ForeignKey("sensors.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String(32), nullable=False, index=True)  # high, low, no_data_timeout, device_offline
    min_value = Column(Float, nullable=True)
    max_value = Column(Float, nullable=True)
    timeout_sec = Column(Integer, nullable=False, default=60)
    debounce_sec = Column(Integer, nullable=False, default=30)
    severity = Column(String(20), nullable=False, default="medium")
    enabled = Column(Boolean, nullable=False, default=True)


class AlarmEvent(Base):
    __tablename__ = "alarm_events"

    id = Column(Integer, primary_key=True)
    alarm_id = Column(Integer, ForeignKey("alarms.id", ondelete="CASCADE"), nullable=False, index=True)
    sensor_id = Column(Integer, ForeignKey("sensors.id", ondelete="CASCADE"), nullable=False, index=True)
    start_time = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    end_time = Column(DateTime(timezone=True), nullable=True)
    value = Column(Float, nullable=True)
    status = Column(String(20), nullable=False, default="ACTIVE")
    message = Column(String(255), nullable=False)


class EventLog(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True)
    type = Column(String(40), nullable=False, index=True)
    description = Column(Text, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(180), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="viewer")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
