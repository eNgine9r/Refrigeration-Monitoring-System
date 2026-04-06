from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path

import requests


@dataclass
class SensorConfig:
    name: str
    base: float
    noise: float
    min_value: float
    max_value: float


@dataclass
class DeviceConfig:
    device_name: str
    protocol: str
    poll_interval: int
    sensors: list[SensorConfig]


class DeviceSimulator:
    def __init__(self, config: DeviceConfig):
        self.config = config

    def read_measurements(self) -> list[dict]:
        values = []
        for sensor in self.config.sensors:
            raw = sensor.base + random.uniform(-sensor.noise, sensor.noise)
            value = max(sensor.min_value, min(sensor.max_value, raw))
            values.append(
                {
                    "device_name": self.config.device_name,
                    "sensor_name": sensor.name,
                    "value": round(value, 2),
                    "quality": "good",
                }
            )
        return values


def load_devices(path: Path) -> list[DeviceSimulator]:
    raw = json.loads(path.read_text())
    simulators: list[DeviceSimulator] = []
    for device in raw.get("devices", []):
        sensors = [
            SensorConfig(
                name=s["name"],
                base=float(s.get("base", 0.0)),
                noise=float(s.get("noise", 1.0)),
                min_value=float(s.get("min", -9999)),
                max_value=float(s.get("max", 9999)),
            )
            for s in device.get("sensors", [])
        ]
        simulators.append(
            DeviceSimulator(
                DeviceConfig(
                    device_name=device["device_name"],
                    protocol=device.get("protocol", "modbus_rtu"),
                    poll_interval=int(device.get("poll_interval", 3)),
                    sensors=sensors,
                )
            )
        )
    return simulators


def send_measurement(base_url: str, payload: dict) -> None:
    response = requests.post(f"{base_url}/data", json=payload, timeout=3)
    response.raise_for_status()


def main() -> None:
    backend_url = os.getenv("BACKEND_URL", "http://backend:8000")
    config_path = Path(os.getenv("DEVICES_CONFIG", "/app/config/devices.json"))
    simulators = load_devices(config_path)

    if not simulators:
        raise RuntimeError("No devices configured in collector config")

    print(f"Loaded {len(simulators)} devices from {config_path}")

    next_run: dict[str, float] = {sim.config.device_name: 0.0 for sim in simulators}

    while True:
        now = time.time()
        for sim in simulators:
            device = sim.config
            if now < next_run[device.device_name]:
                continue
            try:
                for measurement in sim.read_measurements():
                    send_measurement(backend_url, measurement)
                    print(f"sent: {measurement}")
            except Exception as exc:
                print(f"collector warning [{device.device_name}]: {exc}")
            finally:
                next_run[device.device_name] = now + max(2, min(device.poll_interval, 5))
        time.sleep(0.2)


if __name__ == "__main__":
    main()
