"""Monitor baterai pocket device dengan INA219 (I2C) + estimasi persen (plan.md 7.1a)."""
from __future__ import annotations

import asyncio
import logging
import statistics
import time
from collections import deque

log = logging.getLogger(__name__)

REG_CONFIG, REG_SHUNT, REG_BUS, REG_POWER, REG_CURRENT, REG_CALIB = 0, 1, 2, 3, 4, 5
# BRNG=32V, PGA=/8 (±320mV), BADC/SADC=12-bit, mode shunt+bus kontinu
CONFIG_32V = 0x399F


def pct_from_voltage(v_total: float, cells: int, curve: list[list[float]]) -> int:
    """Interpolasi linier tegangan per sel ke persen."""
    v = v_total / max(1, cells)
    pts = sorted(((float(a), float(b)) for a, b in curve), key=lambda p: p[0])
    if v <= pts[0][0]:
        return int(round(pts[0][1]))
    if v >= pts[-1][0]:
        return int(round(pts[-1][1]))
    for (v0, p0), (v1, p1) in zip(pts, pts[1:]):
        if v0 <= v <= v1:
            return int(round(p0 + (p1 - p0) * (v - v0) / (v1 - v0)))
    return 0


class INA219:
    def __init__(self, bus: int, address: int, shunt_ohm: float, max_current_a: float):
        from smbus2 import SMBus
        self.bus = SMBus(bus)
        self.addr = address
        self.current_lsb = max_current_a / 32768.0
        self.cal = int(0.04096 / (self.current_lsb * shunt_ohm))
        self._write(REG_CALIB, self.cal)
        self._write(REG_CONFIG, CONFIG_32V)

    def _write(self, reg: int, value: int) -> None:
        self.bus.write_i2c_block_data(self.addr, reg, [(value >> 8) & 0xFF, value & 0xFF])

    def _read(self, reg: int) -> int:
        hi, lo = self.bus.read_i2c_block_data(self.addr, reg, 2)
        return (hi << 8) | lo

    def read(self) -> tuple[float, float]:
        """Return (tegangan bus V, arus A)."""
        self._write(REG_CALIB, self.cal)  # kalibrasi bisa hilang saat brown-out
        raw_bus = self._read(REG_BUS)
        voltage = (raw_bus >> 3) * 0.004
        raw_cur = self._read(REG_CURRENT)
        if raw_cur > 32767:
            raw_cur -= 65536
        return voltage, raw_cur * self.current_lsb

    def close(self) -> None:
        self.bus.close()


class PowerMonitor:
    """Membaca INA219 tiap interval_s, menghitung median 30 s, publish ke bus topik 'power'."""

    def __init__(self, cfg, state, bus):
        self.cfg = cfg
        self.state = state
        self.bus = bus
        self.sensor: INA219 | None = None
        self._v: deque[tuple[float, float]] = deque()
        self._a: deque[tuple[float, float]] = deque()

    def _open(self) -> None:
        p = self.cfg.section("power")
        self.sensor = INA219(int(p.get("i2c_bus", 3)), int(p.get("address", 0x40)),
                             float(p.get("shunt_ohm", 0.1)), float(p.get("max_current_a", 3.2)))
        log.info("INA219 siap di i2c-%s alamat 0x%02x", p.get("i2c_bus"), int(p.get("address", 0x40)))

    def _read(self) -> tuple[float, float, bool]:
        fake = self.cfg.get("power.fake_voltage")
        if fake is not None:
            return float(fake), 0.8, True
        if self.sensor is None:
            self._open()
        v, a = self.sensor.read()
        return v, a, False

    def sample(self) -> dict | None:
        p = self.cfg.section("power")
        try:
            v, a, fake = self._read()
        except Exception as e:
            log.warning("INA219 gagal dibaca: %s", e)
            self.sensor = None
            self.state.update("power", level="unknown")
            return None
        now = time.time()
        src = ("fake", v) if fake else ("real", None)
        if src != getattr(self, "_src", None):
            # sumber berubah (mis. nilai palsu diganti saat uji) -> jangan campur dengan riwayat lama
            self._v.clear()
            self._a.clear()
            self._src = src
        self._v.append((now, v))
        self._a.append((now, a))
        while self._v and now - self._v[0][0] > 30:
            self._v.popleft()
        while self._a and now - self._a[0][0] > 60:
            self._a.popleft()
        v_med = statistics.median(x for _, x in self._v)
        a_avg = sum(x for _, x in self._a) / len(self._a)
        pct = pct_from_voltage(v_med, int(p.get("cells", 1)), p.get("curve"))
        cap = float(p.get("capacity_mah", 0) or 0)
        remaining_h = None
        if cap > 0 and a_avg > 0.01:
            remaining_h = round((cap / 1000.0) * pct / 100.0 / a_avg, 2)
        if pct < float(p.get("critical_pct", 8)):
            level = "critical"
        elif pct < float(p.get("low_pct", 20)):
            level = "low"
        else:
            level = "normal"
        data = {"voltage": round(v, 3), "voltage_median": round(v_med, 3), "current_a": round(a, 3),
                "power_w": round(v * a, 2), "pct": pct, "level": level, "remaining_h": remaining_h,
                "fake": fake, "ts": now}
        self.state.update("power", enabled=True, **{k: data[k] for k in
                          ("voltage", "current_a", "power_w", "pct", "level", "remaining_h", "fake", "ts")})
        return data

    async def run(self) -> None:
        while True:
            data = await asyncio.to_thread(self.sample)
            if data:
                self.bus.publish("power", data)
            await asyncio.sleep(float(self.cfg.get("power.interval_s", 2)))
