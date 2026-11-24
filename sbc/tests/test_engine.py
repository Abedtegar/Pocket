import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from guardian.engine.rules import BatteryRule, HeartRateRule, glasses_offline_reason
from guardian.engine.zones import ZoneTracker, haversine_m
from guardian.outputs.status_led import decide
from guardian.outputs.telegram import format_message
from guardian.sensors.power import pct_from_voltage
from guardian.state import State

CURVE = [[4.20, 100], [3.85, 60], [3.70, 30], [3.50, 10], [3.30, 0]]


def test_haversine():
    # 0.001 derajat lintang ~ 111 m
    assert abs(haversine_m(-7.28, 112.79, -7.281, 112.79) - 111.2) < 1


def test_zone_enter_transition():
    zt = ZoneTracker()
    zt.set_zones([{"id": 1, "name": "gang", "lat": -7.28, "lon": 112.79, "radius_m": 100, "active": True}])
    assert zt.update(-7.29, 112.79) == []            # luar
    assert len(zt.update(-7.2801, 112.79)) == 1     # masuk
    assert zt.update(-7.2802, 112.79) == []          # tetap di dalam
    assert zt.update(-7.29, 112.79) == []            # keluar
    assert len(zt.update(-7.28, 112.79)) == 1       # masuk lagi


def test_hr_sustain():
    rule = HeartRateRule()
    cfg = {"high_bpm": 120, "low_bpm": 45, "sustain_s": 10, "require_finger": True}
    assert rule.update(130, True, 0, cfg) == []
    assert rule.update(130, True, 5, cfg) == []
    assert rule.update(130, False, 7, cfg) == []     # jari lepas -> reset
    assert rule.update(130, True, 8, cfg) == []
    out = rule.update(130, True, 18, cfg)
    assert out and out[0][0] == "hr_high"
    assert rule.update(0, True, 30, cfg) == []        # bpm 0 bukan hr_low


def test_battery_pct_and_rule():
    assert pct_from_voltage(4.25, 1, CURVE) == 100
    assert pct_from_voltage(3.775, 1, CURVE) == 45
    assert pct_from_voltage(7.4, 2, CURVE) == 30
    assert pct_from_voltage(3.0, 1, CURVE) == 0
    rule = BatteryRule()
    cfg = {"low_pct": 20, "critical_pct": 8, "shutdown_pct": 5}
    assert rule.update(50, cfg) == []
    assert rule.update(19, cfg) == ["battery_low"]
    assert rule.update(18, cfg) == []
    assert rule.update(7, cfg) == ["battery_critical"]
    assert rule.update(4, cfg) == ["shutdown"]
    assert rule.update(30, cfg) == []
    assert rule.update(6, cfg) == ["battery_critical"]   # langsung kritis: low tidak ikut dikirim


def test_offline_reason():
    st = State().snapshot()
    assert glasses_offline_reason(st, 10, 15, True, 0, 30) is None     # masih grace
    assert glasses_offline_reason(st, 40, 15, True, 0, 30) == "no_status"
    st["glasses"]["last_status"] = 39
    st["stream"]["last_frame"] = 39
    assert glasses_offline_reason(st, 40, 15, True, 0, 30) is None
    st["glasses"]["lwt_online"] = False
    assert glasses_offline_reason(st, 40, 15, True, 0, 30) == "lwt"


class _Cfg:
    def __init__(self, d):
        self.d = d

    def get(self, path, default=None):
        return self.d.get(path, default)


def test_led_priority():
    st = State().snapshot()
    cfg = _Cfg({"gps.enabled": True})
    assert decide(st, cfg) == ("blue", "slow")
    st["glasses"]["online"] = True
    assert decide(st, cfg) == ("yellow", "solid")
    st["net"]["internet"] = True
    st["gps"]["fix"] = True
    assert decide(st, cfg) == ("green", "heartbeat")
    st["power"]["level"] = "low"
    assert decide(st, cfg) == ("purple", "slow")
    st["alarm"]["active"] = True
    assert decide(st, cfg) == ("red", "fast")


def test_telegram_format():
    ev = {"type": "panic", "ts": "2026-11-22T09:30:12+07:00", "lat": -7.28, "lon": 112.79, "loc_src": "gps",
          "data": {"bpm": 128, "loc_age_s": 3}}
    msg = format_message(ev, ZoneInfo("Asia/Jakarta"))
    assert "Tombol darurat" in msg
    assert "22-11-2026 09:30:12" in msg
    assert "q=-7.2800,112.7900 (GPS, 3 dtk lalu)" in msg
    assert "128 bpm" in msg


def test_db_roundtrip(tmp_path):
    from guardian.storage.db import Database

    async def run():
        tz = ZoneInfo("Asia/Jakarta")
        db = Database(tmp_path / "t.db", tz)
        await db.init()
        now = datetime.now(tz).isoformat(timespec="seconds")
        await db.insert_event({"id": "a1", "ts": now, "type": "panic", "severity": 3, "data": {"x": 1},
                               "lat": None, "lon": None, "loc_src": "none", "snapshot": None})
        assert await db.unacked_alarms() == 1
        assert (await db.list_events())[0]["data"] == {"x": 1}
        await db.ack_event("a1")
        assert await db.unacked_alarms() == 0
        zid = await db.add_zone("z", -7.28, 112.79, 100)
        await db.update_zone(zid, {"active": False})
        assert (await db.list_zones())[0]["active"] is False
        await db.outbox_add(now, {"event": {"id": "a1"}})
        rows = await db.outbox_list()
        await db.outbox_delete(rows[0]["id"])
        assert await db.outbox_count() == 0
        await db.set_setting("k", {"a": 1})
        assert await db.get_setting("k") == {"a": 1}
        await db.close()

    asyncio.run(run())
