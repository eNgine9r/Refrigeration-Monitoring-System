from sqlalchemy import Column, DateTime, Float, Integer, String, func

from .database import Base


class Measurement(Base):
    __tablename__ = "measurements"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    device_name = Column(String(100), nullable=False, index=True)
    sensor_name = Column(String(100), nullable=False, index=True)
    value = Column(Float, nullable=False)
    quality = Column(String(32), nullable=False, default="good")
