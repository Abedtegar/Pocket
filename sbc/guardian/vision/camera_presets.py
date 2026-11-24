"""Manajemen parameter kamera dua lapis + preset (plan.md 5.6 dan 6.4).

Lapis 1 (sensor ESP32) dikirim via MQTT glasses/camera/set.
Lapis 2 (preprocess OpenCV) di-swap atomik ke Preprocessor.
"""
from __future__ import annotations

import logging
from typing import Any

from .preprocess import PreprocessConfig, Preprocessor

log = logging.getLogger(__name__)

FRAMESIZES = ["QQVGA", "QVGA", "CIF", "VGA", "SVGA"]
BOOL_KEYS = ["awb", "aec", "agc", "hmirror", "vflip", "lenc", "bpc", "wpc", "raw_gma", "dcw"]
INT_RANGES = {
    "quality": (4, 63), "brightness": (-2, 2), "contrast": (-2, 2), "saturation": (-2, 2),
    "sharpness": (-2, 2), "wb_mode": (0, 4), "aec_value": (0, 1200), "ae_level": (-2, 2),
    "agc_gain": (0, 30), "gainceiling": (0, 6),
}


def validate_sensor(partial: dict) -> tuple[dict, dict]:
    """Return (nilai valid, error per key). Nilai di luar rentang ditolak, bukan di-clamp."""
    ok: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for k, v in (partial or {}).items():
        try:
            if k == "framesize":
                fs = str(v).upper()
                if fs not in FRAMESIZES:
                    raise ValueError(f"harus salah satu {FRAMESIZES}")
                ok[k] = fs
            elif k in BOOL_KEYS:
                ok[k] = 1 if (v in (True, 1, "1", "true", "on")) else 0
            elif k in INT_RANGES:
                lo, hi = INT_RANGES[k]
                iv = int(v)
                if not lo <= iv <= hi:
                    raise ValueError(f"di luar rentang {lo}..{hi}")
                ok[k] = iv
            else:
                raise ValueError("parameter tidak dikenal")
        except (TypeError, ValueError) as e:
            errors[k] = str(e)
    return ok, errors


class CameraManager:
    def __init__(self, cfg, db, preprocessor: Preprocessor, mqtt=None, reader=None):
        self.cfg = cfg
        self.db = db
        self.pre = preprocessor
        self.mqtt = mqtt
        self.reader = reader
        self.sensor: dict = {}
        self.active_preset = cfg.get("camera.active_preset", "default")

    async def load(self) -> None:
        default_sensor, _ = validate_sensor(self.cfg.section("camera").get("sensor", {}))
        default_pre = PreprocessConfig.from_dict(self.cfg.section("camera").get("preprocess", {}))
        if await self.db.get_preset("default") is None:
            await self.db.save_preset("default", default_sensor, default_pre.to_dict(), self.cfg.now_iso())
        self.active_preset = await self.db.get_setting("camera.active_preset", self.active_preset)
        cur_sensor = await self.db.get_setting("camera.sensor")
        cur_pre = await self.db.get_setting("camera.preprocess")
        if cur_sensor is None or cur_pre is None:
            preset = await self.db.get_preset(self.active_preset) or await self.db.get_preset("default")
            cur_sensor = cur_sensor or preset["sensor"]
            cur_pre = cur_pre or preset["preprocess"]
        self.sensor = {**default_sensor, **validate_sensor(cur_sensor)[0]}
        self.pre.set_config(PreprocessConfig.from_dict(cur_pre, default_pre))
        log.info("kamera: preset aktif '%s'", self.active_preset)

    # ---- lapis 1 ----
    def get_sensor(self) -> dict:
        return dict(self.sensor)

    async def set_sensor(self, partial: dict) -> dict:
        ok, errors = validate_sensor(partial)
        if ok:
            self.sensor.update(ok)
            await self.db.set_setting("camera.sensor", self.sensor)
            if self.mqtt:
                self.mqtt.set_camera(ok)
        return {"applied": ok, "errors": errors, "sensor": self.get_sensor()}

    def resend_sensor(self) -> None:
        """Dipanggil saat glasses/online = 1 agar ESP dan SBC sinkron."""
        if self.mqtt and self.sensor:
            log.info("mengirim ulang parameter sensor ke kacamata")
            self.mqtt.set_camera(self.sensor)

    # ---- lapis 2 ----
    def get_preprocess(self) -> dict:
        return self.pre.config.to_dict()

    async def set_preprocess(self, partial: dict) -> dict:
        new = PreprocessConfig.from_dict(partial, self.pre.config)  # ValueError -> 400 di API
        self.pre.set_config(new)
        await self.db.set_setting("camera.preprocess", new.to_dict())
        return new.to_dict()

    # ---- preset ----
    async def list_presets(self) -> dict:
        return {"active": self.active_preset, "presets": await self.db.list_presets()}

    async def save_preset(self, name: str) -> dict:
        name = name.strip()[:40]
        if not name:
            raise ValueError("nama preset kosong")
        await self.db.save_preset(name, self.sensor, self.get_preprocess(), self.cfg.now_iso())
        self.active_preset = name
        await self.db.set_setting("camera.active_preset", name)
        return await self.db.get_preset(name)

    async def delete_preset(self, name: str) -> bool:
        if name == "default":
            raise ValueError("preset default tidak boleh dihapus")
        return await self.db.delete_preset(name)

    async def apply_preset(self, name: str) -> dict:
        preset = await self.db.get_preset(name)
        if preset is None:
            raise KeyError(name)
        ok, _ = validate_sensor(preset["sensor"])
        self.sensor.update(ok)
        await self.db.set_setting("camera.sensor", self.sensor)
        if self.mqtt:
            self.mqtt.set_camera(self.sensor)
        new = PreprocessConfig.from_dict(preset["preprocess"], PreprocessConfig())
        self.pre.set_config(new)
        await self.db.set_setting("camera.preprocess", new.to_dict())
        self.active_preset = name
        await self.db.set_setting("camera.active_preset", name)
        return preset

    async def reset_default(self) -> dict:
        """Kembalikan preset default ke nilai config.yaml lalu terapkan."""
        default_sensor, _ = validate_sensor(self.cfg.section("camera").get("sensor", {}))
        default_pre = PreprocessConfig.from_dict(self.cfg.section("camera").get("preprocess", {}))
        await self.db.save_preset("default", default_sensor, default_pre.to_dict(), self.cfg.now_iso())
        return await self.apply_preset("default")
