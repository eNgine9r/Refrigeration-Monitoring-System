from datetime import datetime

from pydantic import BaseModel, Field


class MeasurementIn(BaseModel):
    device_name: str = Field(min_length=1, max_length=100)
    sensor_name: str = Field(min_length=1, max_length=100)
    value: float
    quality: str = Field(default="good", max_length=32)
    timestamp: datetime | None = None


class MeasurementOut(BaseModel):
    id: int
    timestamp: datetime
    device_name: str
    sensor_name: str
    value: float
    quality: str

    class Config:
        from_attributes = True
