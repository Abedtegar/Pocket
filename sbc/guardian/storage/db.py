"""Akses SQLite (aiosqlite) sesuai skema plan.md 6.5."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY, ts TEXT NOT NULL, type TEXT NOT NULL,
  severity INTEGER NOT NULL, data TEXT, lat REAL, lon REAL,
  loc_src TEXT, snapshot TEXT, notified INTEGER DEFAULT 0,
  acknowledged INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE TABLE IF NOT EXISTS hr_samples (ts TEXT, bpm INTEGER, finger INTEGER);
CREATE INDEX IF NOT EXISTS idx_hr_ts ON hr_samples(ts);
CREATE TABLE IF NOT EXISTS gps_track (ts TEXT, lat REAL, lon REAL, sats INTEGER, hdop REAL);
CREATE INDEX IF NOT EXISTS idx_gps_ts ON gps_track(ts);
CREATE TABLE IF NOT EXISTS power_samples (ts TEXT, voltage REAL, current_a REAL, power_w REAL, pct INTEGER);
CREATE INDEX IF NOT EXISTS idx_power_ts ON power_samples(ts);
CREATE TABLE IF NOT EXISTS zones (
  id INTEGER PRIMARY KEY, name TEXT, lat REAL, lon REAL,
  radius_m REAL, active INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS camera_presets (
  name TEXT PRIMARY KEY,
  sensor TEXT NOT NULL,
  preprocess TEXT NOT NULL,
  updated TEXT
);
CREATE TABLE IF NOT EXISTS outbox (id INTEGER PRIMARY KEY, created TEXT, payload TEXT, tries INTEGER DEFAULT 0);
"""

ALARM_TYPES = ("panic", "weapon", "hr_high", "hr_low")


def _event_row(row: aiosqlite.Row) -> dict:
    d = dict(row)
    d["data"] = json.loads(d["data"]) if d.get("data") else {}
    d["notified"] = bool(d.get("notified"))
    d["acknowledged"] = bool(d.get("acknowledged"))
    return d


class Database:
    def __init__(self, path: Path, tz):
        self.path = path
        self.tz = tz
        self.conn: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode=WAL")
        await self.conn.execute("PRAGMA synchronous=NORMAL")
        await self.conn.executescript(SCHEMA)
        await self.conn.commit()

    async def close(self) -> None:
        if self.conn:
            await self.conn.commit()
            await self.conn.close()
            self.conn = None

    def _since(self, minutes: float) -> str:
        return (datetime.now(self.tz) - timedelta(minutes=minutes)).isoformat(timespec="seconds")

    async def _all(self, sql: str, args: tuple = ()) -> list[dict]:
        async with self.conn.execute(sql, args) as cur:
            return [dict(r) for r in await cur.fetchall()]

    # ---- events ----
    async def insert_event(self, ev: dict) -> None:
        await self.conn.execute(
            "INSERT INTO events (id, ts, type, severity, data, lat, lon, loc_src, snapshot, notified, acknowledged)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,0)",
            (ev["id"], ev["ts"], ev["type"], ev["severity"], json.dumps(ev.get("data") or {}),
             ev.get("lat"), ev.get("lon"), ev.get("loc_src"), ev.get("snapshot"), int(ev.get("notified", False))))
        await self.conn.commit()

    async def list_events(self, limit: int = 100, type_: str | None = None, offset: int = 0) -> list[dict]:
        sql = "SELECT * FROM events"
        args: list[Any] = []
        if type_:
            sql += " WHERE type = ?"
            args.append(type_)
        sql += " ORDER BY ts DESC LIMIT ? OFFSET ?"
        args += [limit, offset]
        async with self.conn.execute(sql, args) as cur:
            return [_event_row(r) for r in await cur.fetchall()]

    async def get_event(self, ev_id: str) -> dict | None:
        async with self.conn.execute("SELECT * FROM events WHERE id = ?", (ev_id,)) as cur:
            row = await cur.fetchone()
        return _event_row(row) if row else None

    async def ack_event(self, ev_id: str) -> bool:
        cur = await self.conn.execute("UPDATE events SET acknowledged = 1 WHERE id = ?", (ev_id,))
        await self.conn.commit()
        return cur.rowcount > 0

    async def ack_all(self) -> int:
        cur = await self.conn.execute("UPDATE events SET acknowledged = 1 WHERE acknowledged = 0")
        await self.conn.commit()
        return cur.rowcount

    async def mark_notified(self, ev_id: str) -> None:
        await self.conn.execute("UPDATE events SET notified = 1 WHERE id = ?", (ev_id,))
        await self.conn.commit()

    async def unacked_alarms(self, hours: float = 24) -> int:
        q = ",".join("?" * len(ALARM_TYPES))
        async with self.conn.execute(
                f"SELECT COUNT(*) FROM events WHERE acknowledged = 0 AND type IN ({q}) AND ts >= ?",
                (*ALARM_TYPES, self._since(hours * 60))) as cur:
            return (await cur.fetchone())[0]

    # ---- sampel ----
    async def add_hr(self, ts: str, bpm: int, finger: bool) -> None:
        await self.conn.execute("INSERT INTO hr_samples VALUES (?,?,?)", (ts, int(bpm), int(finger)))
        await self.conn.commit()

    async def hr_since(self, minutes: float) -> list[dict]:
        return await self._all("SELECT ts, bpm, finger FROM hr_samples WHERE ts >= ? ORDER BY ts",
                               (self._since(minutes),))

    async def add_gps(self, ts: str, lat: float, lon: float, sats: int, hdop: float | None) -> None:
        await self.conn.execute("INSERT INTO gps_track VALUES (?,?,?,?,?)", (ts, lat, lon, sats, hdop))
        await self.conn.commit()

    async def track_since(self, minutes: float) -> list[dict]:
        return await self._all("SELECT ts, lat, lon, sats, hdop FROM gps_track WHERE ts >= ? ORDER BY ts",
                               (self._since(minutes),))

    async def add_power(self, ts: str, v: float, a: float, w: float, pct: int | None) -> None:
        await self.conn.execute("INSERT INTO power_samples VALUES (?,?,?,?,?)", (ts, v, a, w, pct))
        await self.conn.commit()

    async def power_since(self, minutes: float) -> list[dict]:
        return await self._all(
            "SELECT ts, voltage, current_a, power_w, pct FROM power_samples WHERE ts >= ? ORDER BY ts",
            (self._since(minutes),))

    async def purge_samples(self, days: int) -> None:
        cutoff = self._since(days * 24 * 60)
        for table in ("hr_samples", "gps_track", "power_samples"):
            await self.conn.execute(f"DELETE FROM {table} WHERE ts < ?", (cutoff,))
        await self.conn.commit()

    # ---- zona ----
    async def list_zones(self) -> list[dict]:
        rows = await self._all("SELECT * FROM zones ORDER BY id")
        for r in rows:
            r["active"] = bool(r["active"])
        return rows

    async def add_zone(self, name: str, lat: float, lon: float, radius_m: float, active: bool = True) -> int:
        cur = await self.conn.execute("INSERT INTO zones (name, lat, lon, radius_m, active) VALUES (?,?,?,?,?)",
                                      (name, lat, lon, radius_m, int(active)))
        await self.conn.commit()
        return cur.lastrowid

    async def update_zone(self, zone_id: int, fields: dict) -> bool:
        allowed = {k: v for k, v in fields.items() if k in ("name", "lat", "lon", "radius_m", "active")}
        if not allowed:
            return False
        if "active" in allowed:
            allowed["active"] = int(bool(allowed["active"]))
        sets = ", ".join(f"{k} = ?" for k in allowed)
        cur = await self.conn.execute(f"UPDATE zones SET {sets} WHERE id = ?", (*allowed.values(), zone_id))
        await self.conn.commit()
        return cur.rowcount > 0

    async def delete_zone(self, zone_id: int) -> bool:
        cur = await self.conn.execute("DELETE FROM zones WHERE id = ?", (zone_id,))
        await self.conn.commit()
        return cur.rowcount > 0

    # ---- settings ----
    async def get_setting(self, key: str, default: Any = None) -> Any:
        async with self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cur:
            row = await cur.fetchone()
        return json.loads(row[0]) if row else default

    async def set_setting(self, key: str, value: Any) -> None:
        await self.conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                                (key, json.dumps(value)))
        await self.conn.commit()

    # ---- preset kamera ----
    async def list_presets(self) -> list[dict]:
        rows = await self._all("SELECT * FROM camera_presets ORDER BY name")
        for r in rows:
            r["sensor"] = json.loads(r["sensor"])
            r["preprocess"] = json.loads(r["preprocess"])
        return rows

    async def get_preset(self, name: str) -> dict | None:
        async with self.conn.execute("SELECT * FROM camera_presets WHERE name = ?", (name,)) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["sensor"], d["preprocess"] = json.loads(d["sensor"]), json.loads(d["preprocess"])
        return d

    async def save_preset(self, name: str, sensor: dict, preprocess: dict, updated: str) -> None:
        await self.conn.execute(
            "INSERT INTO camera_presets (name, sensor, preprocess, updated) VALUES (?,?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET sensor = excluded.sensor, preprocess = excluded.preprocess, "
            "updated = excluded.updated", (name, json.dumps(sensor), json.dumps(preprocess), updated))
        await self.conn.commit()

    async def delete_preset(self, name: str) -> bool:
        cur = await self.conn.execute("DELETE FROM camera_presets WHERE name = ?", (name,))
        await self.conn.commit()
        return cur.rowcount > 0

    # ---- outbox ----
    async def outbox_add(self, created: str, payload: dict) -> None:
        await self.conn.execute("INSERT INTO outbox (created, payload, tries) VALUES (?,?,0)",
                                (created, json.dumps(payload)))
        await self.conn.commit()

    async def outbox_list(self, limit: int = 20) -> list[dict]:
        rows = await self._all("SELECT * FROM outbox ORDER BY id LIMIT ?", (limit,))
        for r in rows:
            r["payload"] = json.loads(r["payload"])
        return rows

    async def outbox_count(self) -> int:
        async with self.conn.execute("SELECT COUNT(*) FROM outbox") as cur:
            return (await cur.fetchone())[0]

    async def outbox_delete(self, row_id: int) -> None:
        await self.conn.execute("DELETE FROM outbox WHERE id = ?", (row_id,))
        await self.conn.commit()

    async def outbox_fail(self, row_id: int) -> None:
        await self.conn.execute("UPDATE outbox SET tries = tries + 1 WHERE id = ?", (row_id,))
        await self.conn.commit()
