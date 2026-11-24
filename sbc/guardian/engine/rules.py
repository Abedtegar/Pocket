"""Aturan per jenis event (plan.md 7.1) dan RuleRunner yang menghubungkan bus -> EventEngine."""
from __future__ import annotations

import asyncio
import logging
import time

from .zones import ZoneTracker

log = logging.getLogger(__name__)


class SustainTracker:
    """Kondisi harus benar terus-menerus selama sustain_s sebelum memicu."""

    def __init__(self) -> None:
        self.since: float | None = None

    def update(self, cond: bool, now: float, sustain_s: float) -> bool:
        if not cond:
            self.since = None
            return False
        if self.since is None:
            self.since = now
        if now - self.since >= sustain_s:
            self.since = now  # picu lagi setelah sustain_s berikutnya (dibatasi cooldown)
            return True
        return False


class HeartRateRule:
    def __init__(self) -> None:
        self.high = SustainTracker()
        self.low = SustainTracker()

    def update(self, bpm: int, finger: bool, now: float, cfg: dict) -> list[tuple[str, dict]]:
        valid = finger or not cfg.get("require_finger", True)
        sustain = float(cfg.get("sustain_s", 10))
        out = []
        if self.high.update(valid and bpm > float(cfg.get("high_bpm", 120)), now, sustain):
            out.append(("hr_high", {"bpm": bpm, "threshold": cfg.get("high_bpm"), "sustain_s": sustain}))
        if self.low.update(valid and 0 < bpm < float(cfg.get("low_bpm", 45)), now, sustain):
            out.append(("hr_low", {"bpm": bpm, "threshold": cfg.get("low_bpm"), "sustain_s": sustain}))
        return out


class BatteryRule:
    """Memicu sekali saat melewati ambang turun; aktif kembali setelah naik 3% di atas ambang."""

    HYST = 3

    def __init__(self) -> None:
        self.armed = {"battery_low": True, "battery_critical": True, "shutdown": True}

    def update(self, pct: int, cfg: dict) -> list[str]:
        out = []
        for key, thr_key in (("battery_low", "low_pct"), ("battery_critical", "critical_pct"),
                             ("shutdown", "shutdown_pct")):
            thr = float(cfg.get(thr_key, 0))
            if pct < thr and self.armed[key]:
                self.armed[key] = False
                out.append(key)
            elif pct >= thr + self.HYST:
                self.armed[key] = True
        if "battery_critical" in out and "battery_low" in out:
            out.remove("battery_low")
        return out


class TransitionRule:
    """Memicu sekali saat kondisi 'buruk' mulai; aktif kembali saat kondisi pulih."""

    def __init__(self) -> None:
        self.bad = False

    def update(self, bad: bool) -> bool:
        fired = bad and not self.bad
        self.bad = bad
        return fired


def glasses_offline_reason(st: dict, now: float, timeout: float, mqtt_enabled: bool,
                           started: float, grace: float) -> str | None:
    """Return alasan offline atau None jika kacamata dianggap online."""
    g, s = st["glasses"], st["stream"]
    if mqtt_enabled and g.get("lwt_online") is False:
        return "lwt"
    if now - started < grace:
        return None
    if mqtt_enabled:
        last = g.get("last_status")
        if last is None or now - last > timeout:
            return "no_status"
    last_frame = s.get("last_frame")
    if last_frame is None or now - last_frame > timeout:
        return "no_frame"
    return None


class RuleRunner:
    def __init__(self, cfg, state, bus, engine, db):
        self.cfg = cfg
        self.state = state
        self.bus = bus
        self.engine = engine
        self.db = db
        self.hr = HeartRateRule()
        self.battery = BatteryRule()
        self.offline = TransitionRule()
        self.gps_lost = TransitionRule()
        self.zones = ZoneTracker()
        self._last_hr_store = 0.0
        self._last_gps_store = 0.0
        self._last_power_store = 0.0
        self._shutdown_started = False

    async def start(self) -> None:
        await self.reload_zones()
        self.bus.on("hr", self._on_hr)
        self.bus.on("power", self._on_power)
        self.bus.on("glasses_online", self._on_glasses_online)

    async def reload_zones(self) -> None:
        self.zones.set_zones(await self.db.list_zones())

    # ---- handler bus ----
    async def _on_hr(self, msg: dict) -> None:
        now = time.time()
        for typ, data in self.hr.update(msg["bpm"], msg["finger"], now, self.cfg.section("heart_rate")):
            await self.engine.emit(typ, data)
        if now - self._last_hr_store >= 5:
            self._last_hr_store = now
            await self.db.add_hr(self.cfg.now_iso(), msg["bpm"], msg["finger"])

    async def _on_power(self, data: dict) -> None:
        now = time.time()
        p = self.cfg.section("power")
        for key in self.battery.update(data["pct"], p):
            info = {"pct": data["pct"], "voltage": data["voltage_median"]}
            if key == "shutdown":
                await self._shutdown(data)
            else:
                await self.engine.emit(key, info)
        if now - self._last_power_store >= 30:
            self._last_power_store = now
            await self.db.add_power(self.cfg.now_iso(), data["voltage"], data["current_a"],
                                    data["power_w"], data["pct"])

    def _on_glasses_online(self, online: bool) -> None:
        if online:
            self.offline.update(False)

    async def _shutdown(self, data: dict) -> None:
        if self._shutdown_started:
            return
        self._shutdown_started = True
        p = self.cfg.section("power")
        dry = (not p.get("shutdown_enabled", True)) or p.get("fake_voltage") is not None
        log.critical("baterai %s%% < shutdown_pct -> shutdown aman%s", data["pct"], " (DRY RUN)" if dry else "")
        await self.engine.final_message(
            f"🔋 Baterai pocket device {data['pct']}% ({data['voltage_median']:.2f} V). "
            f"Perangkat dimatikan untuk melindungi baterai.")
        if dry:
            log.warning("DRY RUN: perintah shutdown tidak dijalankan")
            self._shutdown_started = False
            return
        await self.engine.flush()
        cmd = p.get("shutdown_command") or ["sudo", "/sbin/shutdown", "-h", "now"]
        proc = await asyncio.create_subprocess_exec(*cmd)
        await proc.wait()

    # ---- pemeriksaan periodik (1 Hz) ----
    async def periodic(self) -> None:
        while True:
            try:
                await self._tick()
            except Exception:
                log.exception("rule tick gagal")
            await asyncio.sleep(1.0)

    async def _tick(self) -> None:
        now = time.time()
        st = self.state.snapshot()
        g = self.cfg.section("glasses")
        reason = glasses_offline_reason(st, now, float(g.get("offline_timeout_s", 15)),
                                        bool(self.cfg.get("mqtt.enabled", True)), self.state.started,
                                        float(g.get("startup_grace_s", 30)))
        self.state.update("glasses", online=reason is None, offline_reason=reason)
        if self.offline.update(reason is not None):
            await self.engine.emit("glasses_offline", {"reason": reason})

        # GPS
        if self.cfg.get("gps.enabled", True):
            gps = st["gps"]
            stale = float(self.cfg.get("gps.stale_s", 30))
            fix_ts = gps.get("fix_ts")
            fresh = fix_ts is not None and now - fix_ts <= stale and gps.get("fix")
            in_grace = now - self.state.started < stale
            if self.gps_lost.update(not fresh and not in_grace):
                age = None if fix_ts is None else int(now - fix_ts)
                await self.engine.emit("gps_lost", {"last_fix_age_s": age})
            if fresh:
                for z in self.zones.update(gps["lat"], gps["lon"]):
                    await self.engine.emit("zone_enter", {"zone_id": z["id"], "zone": z["name"],
                                                          "radius_m": z["radius_m"],
                                                          "distance_m": z["distance_m"]},
                                           cooldown_key=f"zone_enter:{z['id']}")
                if now - self._last_gps_store >= 10:
                    self._last_gps_store = now
                    await self.db.add_gps(self.cfg.now_iso(), gps["lat"], gps["lon"],
                                          gps.get("sats") or 0, gps.get("hdop"))
