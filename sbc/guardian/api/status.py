"""Bentuk JSON status terkini (dipakai GET /api/status dan WebSocket)."""
from __future__ import annotations

import time


def _age(ts):
    return None if ts is None else round(time.time() - ts, 1)


def build_status(ctx) -> dict:
    st = ctx.state.snapshot()
    g, s, hr, gps, pw, v = st["glasses"], st["stream"], st["hr"], st["gps"], st["power"], st["vision"]
    return {
        "time": ctx.cfg.now_iso(),
        "glasses": {
            "online": g["online"], "offline_reason": g["offline_reason"], "lwt_online": g["lwt_online"],
            "batt_mv": g["batt_mv"], "rssi": g["rssi"], "uptime": g["uptime"], "heap": g["heap"],
            "cam_ok": g["cam_ok"], "status_age_s": _age(g["last_status"]),
        },
        "stream": {"connected": s["connected"], "fps": s["fps"], "frame_age_s": _age(s["last_frame"])},
        "hr": {"bpm": hr["bpm"], "finger": hr["finger"], "age_s": _age(hr["ts"])},
        "gps": {"enabled": ctx.cfg.get("gps.enabled", True), "fix": gps["fix"], "lat": gps["lat"],
                "lon": gps["lon"], "sats": gps["sats"], "hdop": gps["hdop"], "fix_age_s": _age(gps["fix_ts"])},
        "power": {k: pw.get(k) for k in ("enabled", "voltage", "current_a", "power_w", "pct", "level",
                                         "remaining_h", "fake")},
        "vision": {"enabled": v["enabled"], "model_ok": v["model_ok"], "fps": v["fps"],
                   "latency_ms": v["latency_ms"], "detections": v["detections"], "paused": v["paused"],
                   "error": v["error"]},
        "led": st["led"],
        "internet": st["net"]["internet"],
        "mqtt": st["mqtt"]["connected"],
        "alarm": st["alarm"],
        "recorder": st["recorder"],
        "camera_preset": ctx.camera.active_preset if ctx.camera else None,
    }
