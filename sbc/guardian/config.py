"""Memuat config.yaml + .env dan menyediakan akses thread-safe.

Nilai yang boleh diubah dari web (lihat EDITABLE) disimpan di tabel `settings`
dengan key `config_overrides` dan di-merge di atas config.yaml saat start.
"""
from __future__ import annotations

import copy
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent  # folder sbc/

# Bagian config yang boleh diubah lewat PUT /api/settings: section -> daftar key (None = semua key)
EDITABLE: dict[str, list[str] | None] = {
    "heart_rate": ["high_bpm", "low_bpm", "sustain_s", "require_finger"],
    "vision": ["conf", "iou", "temporal_n", "temporal_m", "max_fps", "classes"],
    "alerts": None,
    "power": ["low_pct", "critical_pct", "shutdown_pct", "capacity_mah", "fake_voltage"],
    "glasses": ["offline_timeout_s"],
    "gps": ["stale_s"],
}


def deep_merge(base: dict, extra: dict) -> dict:
    """Merge `extra` ke dalam `base` secara rekursif (mengubah base)."""
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def _coerce(value: Any, like: Any) -> Any:
    """Paksa tipe `value` mengikuti tipe nilai lama `like`."""
    if like is None or value is None:
        return value
    if isinstance(like, bool):
        if isinstance(value, str):
            return value.lower() in ("1", "true", "yes", "on")
        return bool(value)
    if isinstance(like, int) and not isinstance(like, bool):
        return int(float(value))
    if isinstance(like, float):
        return float(value)
    if isinstance(like, list) and isinstance(value, str):
        return [s.strip() for s in value.split(",") if s.strip()]
    return value


class Config:
    def __init__(self, data: dict, base_dir: Path = BASE_DIR):
        self._data = data
        self._lock = threading.RLock()
        self.base_dir = base_dir
        self.tz = ZoneInfo(data.get("timezone", "Asia/Jakarta"))
        self.env = {
            "TELEGRAM_TOKEN": os.getenv("TELEGRAM_TOKEN", ""),
            "TELEGRAM_CHAT_ID": os.getenv("TELEGRAM_CHAT_ID", os.getenv("CHAT_ID", "")),
            "WEB_PASSWORD_HASH": os.getenv("WEB_PASSWORD_HASH", ""),
            "SESSION_SECRET": os.getenv("SESSION_SECRET", ""),
        }

    # ---- akses ----
    def get(self, path: str, default: Any = None) -> Any:
        with self._lock:
            node: Any = self._data
            for part in path.split("."):
                if not isinstance(node, dict) or part not in node:
                    return default
                node = node[part]
            return copy.deepcopy(node)

    def section(self, name: str) -> dict:
        return self.get(name, {}) or {}

    def as_dict(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._data)

    def set(self, path: str, value: Any) -> None:
        with self._lock:
            parts = path.split(".")
            node = self._data
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = value

    def merge(self, partial: dict) -> None:
        with self._lock:
            deep_merge(self._data, copy.deepcopy(partial))

    def path(self, rel: str) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else self.base_dir / p

    def now(self) -> datetime:
        return datetime.now(self.tz)

    def now_iso(self) -> str:
        return self.now().isoformat(timespec="seconds")

    # ---- settings yang bisa diubah dari web ----
    def editable_view(self) -> dict:
        out: dict = {}
        for sec, keys in EDITABLE.items():
            data = self.section(sec)
            out[sec] = data if keys is None else {k: data.get(k) for k in keys}
        return out

    def validate_overrides(self, partial: dict) -> dict:
        """Saring dan konversi tipe; buang key yang tidak boleh diubah."""
        clean: dict = {}
        for sec, values in (partial or {}).items():
            if sec not in EDITABLE or not isinstance(values, dict):
                continue
            allowed = EDITABLE[sec]
            current = self.section(sec)
            for k, v in values.items():
                if allowed is not None and k not in allowed:
                    continue
                old = current.get(k)
                if isinstance(old, dict) and isinstance(v, dict):
                    clean.setdefault(sec, {})[k] = {
                        kk: _coerce(vv, old.get(kk, vv)) for kk, vv in v.items()
                    }
                else:
                    try:
                        clean.setdefault(sec, {})[k] = _coerce(v, old)
                    except (TypeError, ValueError):
                        continue
        return clean


def load_config(base_dir: Path = BASE_DIR, filename: str = "config.yaml") -> Config:
    load_dotenv(base_dir / ".env")
    with open(base_dir / filename, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return Config(data, base_dir)
