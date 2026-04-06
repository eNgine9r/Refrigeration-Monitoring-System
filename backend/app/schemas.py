from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


QualityType = Literal["OK", "ERROR", "OFFLINE"]
RoleType = Literal["admin", "operator", "viewer"]
AlarmType = Literal["high", "low", "no_data_timeout", "device_offline"]


class DeviceBase(BaseModel):
    name: str
    protocol: str
    port: str
    slave_id: int
    poll_interval: int = Field(default=5, ge=1, le=60)


class DeviceCreate(DeviceBase):
    pass


class DeviceUpdate(BaseModel):
    protocol: str | None = None
    port: str | None = None
    slave_id: int | None = None
    poll_interval: int | None = Field(default=None, ge=1, le=60)
    status: str | None = None


class DeviceOut(DeviceBase):
    id: int
    status: str
    last_seen: datetime | None

    class Config:
        from_attributes = True


class SensorBase(BaseModel):
    device_id: int
    name: str
    unit: str = ""
    data_type: str = "float32"
    register_address: int | None = None
    scale: float = 1.0
    is_active: bool = True


class SensorCreate(SensorBase):
    pass


class SensorUpdate(BaseModel):
    unit: str | None = None
    data_type: str | None = None
    register_address: int | None = None
    scale: float | None = None
    is_active: bool | None = None


class SensorOut(SensorBase):
    id: int
    last_seen: datetime | None = None

    class Config:
        from_attributes = True


class AlarmBase(BaseModel):
    sensor_id: int
    type: AlarmType
    min_value: float | None = None
    max_value: float | None = None
    timeout_sec: int = Field(default=60, ge=5, le=3600)
    debounce_sec: int = Field(default=30, ge=30, le=60)
    severity: str = "medium"
    enabled: bool = True


class AlarmCreate(AlarmBase):
    pass


class AlarmUpdate(BaseModel):
    min_value: float | None = None
    max_value: float | None = None
    timeout_sec: int | None = Field(default=None, ge=5, le=3600)
    debounce_sec: int | None = Field(default=None, ge=30, le=60)
    severity: str | None = None
    enabled: bool | None = None


class AlarmOut(AlarmBase):
    id: int

    class Config:
        from_attributes = True


class AlarmEventOut(BaseModel):
    id: int
    alarm_id: int
    sensor_id: int
    start_time: datetime
    end_time: datetime | None
    value: float | None
    status: str
    message: str

    class Config:
        from_attributes = True


class MeasurementIn(BaseModel):
    sensor_id: int | None = None
    device_name: str | None = None
    sensor_name: str | None = None
    value: float
    quality: QualityType = "OK"
    timestamp: datetime | None = None


class MeasurementOut(BaseModel):
    id: int
    timestamp: datetime
    sensor_id: int
    value: float
    quality: QualityType

    class Config:
        from_attributes = True


class EventOut(BaseModel):
    id: int
    type: str
    description: str
    user_id: int | None
    timestamp: datetime

    class Config:
        from_attributes = True


class UserCreate(BaseModel):
    email: str
    password: str = Field(min_length=6)
    role: RoleType = "viewer"


class UserOut(BaseModel):
    id: int
    email: str
    role: RoleType
    is_active: bool

    class Config:
        from_attributes = True


class LoginInput(BaseModel):
    email: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
