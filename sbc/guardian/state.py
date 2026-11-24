"""Status terkini sistem yang dibagi antar thread (dibaca API, LED, rules)."""
from __future__ import annotations

import copy
import threading
import time
from typing import Any


class State:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.started = time.time()
        self._d: dict[str, dict[str, Any]] = {
            "glasses": {
                "online": False,        # status gabungan (LWT + timeout)
                "lwt_online": None,     # nilai terakhir glasses/online
                "last_status": None,    # time.time() pesan status terakhir
                "last_hr": None,
                "batt_mv": None, "rssi": None, "uptime": None, "heap": None, "cam_ok": None,
                "offline_reason": None,
            },
            "stream": {"connected": False, "fps": 0.0, "last_frame": None, "width": None, "height": None},
            "camera": {"esp_state": None},
            "hr": {"bpm": 0, "finger": False, "ir": None, "ts": None},
            "gps": {"enabled": False, "fix": False, "lat": None, "lon": None, "sats": 0,
                    "hdop": None, "fix_ts": None, "last_sentence": None},
            "power": {"enabled": False, "voltage": None, "current_a": None, "power_w": None,
                      "pct": None, "level": "unknown", "remaining_h": None, "fake": False, "ts": None},
            "vision": {"enabled": False, "model_ok": False, "fps": 0.0, "latency_ms": {},
                       "detections": [], "paused": False, "error": None},
            "led": {"color": "off", "pattern": "solid"},
            "net": {"internet": False, "checked": None},
            "alarm": {"active": False, "last_event": None},
            "recorder": {"active": False, "session": None, "frames": 0, "fps": 0.0},
            "mqtt": {"connected": False},
        }

    def update(self, section: str, **kw: Any) -> None:
        with self._lock:
            self._d.setdefault(section, {}).update(kw)

    def get(self, section: str) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._d.get(section, {}))

    def value(self, section: str, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._d.get(section, {}).get(key, default)

    def snapshot(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return copy.deepcopy(self._d)
