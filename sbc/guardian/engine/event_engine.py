"""Event engine: cooldown, severity, lokasi, snapshot, simpan, dan dispatch ke semua output."""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Callable

log = logging.getLogger(__name__)

SEVERITY = {
    "panic": 3,
    "weapon": 2, "hr_high": 2, "hr_low": 2, "glasses_offline": 2, "battery_critical": 2,
    "zone_enter": 1, "gps_lost": 1, "battery_low": 1,
}
SOUNDS = {
    "panic": "panic.wav", "weapon": "weapon.wav", "hr_high": "hr.wav", "hr_low": "hr.wav",
    "zone_enter": "zone.wav", "glasses_offline": "offline.wav",
    "battery_low": "battery.wav", "battery_critical": "battery.wav",
}
NO_TELEGRAM = {"gps_lost"}            # status di web saja
SNAPSHOT_TYPES = {"panic", "weapon"}  # snapshot diambil dari kamera
ALARM_TYPES = {"panic", "weapon", "hr_high", "hr_low"}  # LED merah kedip sampai di-ack


class EventEngine:
    def __init__(self, cfg, state, bus, db, snapshots, telegram, speaker,
                 frame_source: Callable[[], bytes | None]):
        self.cfg = cfg
        self.state = state
        self.bus = bus
        self.db = db
        self.snapshots = snapshots
        self.telegram = telegram
        self.speaker = speaker
        self.frame_source = frame_source
        self._last: dict[str, float] = {}
        self._tasks: set[asyncio.Task] = set()

    # ---- pemicu dari thread lain ----
    def trigger_panic_threadsafe(self) -> None:
        """Dipanggil langsung dari thread tombol panic."""
        loop = self.bus.loop
        if loop and not loop.is_closed():
            loop.call_soon_threadsafe(self._spawn, self.emit("panic", {"source": "button"}))

    def on_detection_threadsafe(self, det: dict, jpeg: bytes) -> None:
        """Dipanggil thread vision saat deteksi lolos filter temporal."""
        loop = self.bus.loop
        if loop and not loop.is_closed():
            data = {"label": det["label"], "conf": det["conf"], "box": det["box"]}
            loop.call_soon_threadsafe(self._spawn, self.emit("weapon", data, snapshot=jpeg))

    def _spawn(self, coro) -> None:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # ---- lokasi ----
    def location(self) -> dict:
        gps = self.state.get("gps")
        fix_ts = gps.get("fix_ts")
        if fix_ts is None or gps.get("lat") is None:
            return {"lat": None, "lon": None, "loc_src": "none", "loc_age_s": None}
        age = time.time() - fix_ts
        src = "gps" if age <= float(self.cfg.get("gps.stale_s", 30)) else "last_known"
        return {"lat": gps["lat"], "lon": gps["lon"], "loc_src": src, "loc_age_s": int(age)}

    # ---- inti ----
    async def emit(self, type_: str, data: dict | None = None, snapshot: bytes | None = None,
                   cooldown_key: str | None = None, force: bool = False) -> dict | None:
        key = cooldown_key or type_
        cooldown = float(self.cfg.get(f"alerts.cooldown_s.{type_}", 60) or 0)
        now = time.monotonic()
        if not force and key in self._last and now - self._last[key] < cooldown:
            log.debug("event %s diredam cooldown", key)
            return None
        self._last[key] = now

        when = self.cfg.now()
        ev_id = uuid.uuid4().hex[:12]
        loc = self.location()
        data = dict(data or {})
        hr = self.state.get("hr")
        if hr.get("finger") and hr.get("bpm"):
            data.setdefault("bpm", hr["bpm"])
        if loc["loc_age_s"] is not None:
            data["loc_age_s"] = loc["loc_age_s"]
        ev = {
            "id": ev_id, "ts": when.isoformat(timespec="seconds"), "type": type_,
            "severity": SEVERITY.get(type_, 1), "data": data,
            "lat": loc["lat"], "lon": loc["lon"], "loc_src": loc["loc_src"],
            "snapshot": None, "notified": False, "acknowledged": False,
        }
        if snapshot is None and type_ in SNAPSHOT_TYPES:
            snapshot = self.frame_source()
        if snapshot:
            try:
                ev["snapshot"] = await asyncio.to_thread(self.snapshots.save, snapshot, ev_id, when)
            except Exception:
                log.exception("gagal menyimpan snapshot")
        log.warning("EVENT %s sev=%d %s", type_, ev["severity"], data)

        # suara dan LED lebih dulu (paling cepat dirasakan pemakai)
        sound = SOUNDS.get(type_)
        if sound and self.speaker:
            self.speaker.play(sound, priority=ev["severity"])
        if type_ in ALARM_TYPES:
            self.state.update("alarm", active=True, last_event=ev_id)

        try:
            await self.db.insert_event(ev)
        except Exception:
            log.exception("gagal menyimpan event")
        self.bus.publish("event", ev)

        if type_ not in NO_TELEGRAM and self.telegram and self.telegram.enabled:
            self._spawn(self._notify(ev))
        return ev

    async def _notify(self, ev: dict) -> None:
        if await self.telegram.notify(ev):
            ev["notified"] = True
            await self.db.mark_notified(ev["id"])
            self.bus.publish("event_update", {"id": ev["id"], "notified": True})

    async def ack(self, ev_id: str) -> bool:
        ok = await self.db.ack_event(ev_id)
        await self.refresh_alarm()
        self.bus.publish("event_update", {"id": ev_id, "acknowledged": True})
        return ok

    async def ack_all(self) -> int:
        n = await self.db.ack_all()
        await self.refresh_alarm()
        self.bus.publish("event_update", {"id": "*", "acknowledged": True})
        return n

    async def refresh_alarm(self) -> None:
        active = await self.db.unacked_alarms() > 0
        self.state.update("alarm", active=active)

    async def final_message(self, text: str) -> None:
        """Pesan terakhir sebelum shutdown (langsung, tanpa antre)."""
        if self.speaker:
            self.speaker.play("battery.wav", priority=2)
        if self.telegram and self.telegram.enabled:
            try:
                await asyncio.wait_for(self.telegram.send_text(text), 15)
            except Exception as e:
                log.warning("pesan terakhir gagal: %s", e)

    async def flush(self) -> None:
        if self._tasks:
            await asyncio.wait(list(self._tasks), timeout=10)
        await self.db.close()
