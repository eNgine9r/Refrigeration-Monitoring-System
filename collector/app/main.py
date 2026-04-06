from __future__ import annotations

import json
import os
import queue
import random
import threading
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
    port: str
    slave_id: int
    poll_interval: int
    sensors: list[SensorConfig]


class DeviceAdapter:
    def __init__(self, config: DeviceConfig):
        self.config = config

    def read_registers(self, timeout: float) -> list[dict]:
        if random.random() < 0.04:
            time.sleep(timeout + 0.05)
            raise TimeoutError("device response timeout")
        if random.random() < 0.03:
            raise RuntimeError("simulated bus error")

        rows = []
        for sensor in self.config.sensors:
            raw = sensor.base + random.uniform(-sensor.noise, sensor.noise)
            value = max(sensor.min_value, min(sensor.max_value, raw))
            rows.append(
                {
                    "device_name": self.config.device_name,
                    "sensor_name": sensor.name,
                    "value": round(value, 2),
                    "quality": "OK",
                }
            )
        return rows


class CollectorRuntime:
    def __init__(self, config_path: Path, backend_url: str):
        self.config_path = config_path
        self.backend_url = backend_url.rstrip("/")
        self.data_queue: queue.Queue[dict] = queue.Queue(maxsize=30000)
        self.stop_event = threading.Event()
        self.ports: dict[str, list[DeviceAdapter]] = {}
        self.buffer_file = Path("/app/data/local_buffer.jsonl")
        self.timeout_sec = float(os.getenv("DEVICE_TIMEOUT_SEC", "1.0"))

    def load(self) -> None:
        payload = json.loads(self.config_path.read_text())
        ports: dict[str, list[DeviceAdapter]] = {}
        for dev in payload.get("devices", []):
            sensors = [
                SensorConfig(
                    name=s["name"],
                    base=float(s.get("base", 0)),
                    noise=float(s.get("noise", 1)),
                    min_value=float(s.get("min", -9999)),
                    max_value=float(s.get("max", 9999)),
                )
                for s in dev.get("sensors", [])
            ]
            adapter = DeviceAdapter(
                DeviceConfig(
                    device_name=dev["device_name"],
                    protocol=dev.get("protocol", "modbus_rtu"),
                    port=dev.get("port", "RS485_1"),
                    slave_id=int(dev.get("slave_id", 1)),
                    poll_interval=max(2, min(int(dev.get("poll_interval", 5)), 5)),
                    sensors=sensors,
                )
            )
            ports.setdefault(adapter.config.port, []).append(adapter)
        self.ports = ports

    def worker(self, port_name: str, devices: list[DeviceAdapter]) -> None:
        next_run = {d.config.device_name: 0.0 for d in devices}
        while not self.stop_event.is_set():
            now = time.time()
            for device in devices:
                name = device.config.device_name
                if now < next_run[name]:
                    continue

                success = False
                for attempt in range(3):
                    try:
                        rows = device.read_registers(timeout=self.timeout_sec)
                        for row in rows:
                            self.data_queue.put(row, timeout=1)
                        success = True
                        break
                    except Exception as exc:
                        if attempt == 2:
                            offline_row = {
                                "device_name": name,
                                "sensor_name": "device_status",
                                "value": 0.0,
                                "quality": "OFFLINE",
                            }
                            self.data_queue.put(offline_row, timeout=1)
                            print(f"[{port_name}] {name} OFFLINE after retries: {exc}")
                        else:
                            time.sleep(0.1)

                if not success:
                    pass
                next_run[name] = now + device.config.poll_interval
            time.sleep(0.1)

    def flush_batch(self, rows: list[dict]) -> bool:
        if not rows:
            return True
        try:
            resp = requests.post(f"{self.backend_url}/data/batch", json=rows, timeout=5)
            resp.raise_for_status()
            return True
        except Exception as exc:
            print(f"batch send failed ({len(rows)} rows): {exc}")
            return False

    def append_local_buffer(self, rows: list[dict]) -> None:
        self.buffer_file.parent.mkdir(parents=True, exist_ok=True)
        with self.buffer_file.open("a", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")

    def read_local_buffer(self, limit: int = 2000) -> list[dict]:
        if not self.buffer_file.exists():
            return []
        lines = self.buffer_file.read_text(encoding="utf-8").splitlines()
        take = lines[:limit]
        remain = lines[limit:]
        self.buffer_file.write_text("\n".join(remain) + ("\n" if remain else ""), encoding="utf-8")
        return [json.loads(line) for line in take]

    def sender(self) -> None:
        while not self.stop_event.is_set():
            batch: list[dict] = []
            start = time.time()
            while time.time() - start < 1.5 and len(batch) < 1500:
                try:
                    batch.append(self.data_queue.get(timeout=0.2))
                except queue.Empty:
                    break

            replay = self.read_local_buffer(limit=1000)
            if replay:
                batch = replay + batch

            if not batch:
                continue

            ok = self.flush_batch(batch)
            if not ok:
                self.append_local_buffer(batch)

    def run(self) -> None:
        self.load()
        print(f"ports loaded: {', '.join(self.ports.keys())}")
        threads: list[threading.Thread] = []
        for port_name, devices in self.ports.items():
            t = threading.Thread(target=self.worker, args=(port_name, devices), daemon=True)
            t.start()
            threads.append(t)
        sender_t = threading.Thread(target=self.sender, daemon=True)
        sender_t.start()
        threads.append(sender_t)

        while True:
            time.sleep(1)


def main() -> None:
    backend_url = os.getenv("BACKEND_URL", "http://backend:8000")
    config_path = Path(os.getenv("DEVICES_CONFIG", "/app/config/devices.json"))
    runtime = CollectorRuntime(config_path, backend_url)
    runtime.run()


if __name__ == "__main__":
    main()
