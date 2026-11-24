"""Pra-pemrosesan OpenCV lapis 2 (sebelum YOLO), bisa diubah dari web tanpa restart.

Konfigurasi bersifat immutable dan di-swap secara atomik: frame berikutnya
langsung memakai konfigurasi baru.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any

import cv2
import numpy as np


def _clamp(v: Any, lo: float, hi: float, cast=float):
    return cast(min(max(cast(v), lo), hi))


@dataclass(frozen=True)
class PreprocessConfig:
    enabled: bool = True
    rotate: int = 0
    flip: str = "none"
    brightness: float = 0.0
    contrast: float = 1.0
    saturation: float = 1.0
    gamma: float = 1.0
    clahe: bool = False
    clahe_clip: float = 2.0
    sharpen: float = 0.0
    denoise: bool = False
    roi: tuple[float, float, float, float] | None = None

    @classmethod
    def from_dict(cls, d: dict | None, base: "PreprocessConfig | None" = None) -> "PreprocessConfig":
        """Buat config dari dict (boleh sebagian); nilai di luar rentang di-clamp, nilai rusak -> ValueError."""
        cfg = base or cls()
        d = d or {}
        kw: dict[str, Any] = {}
        if "enabled" in d:
            kw["enabled"] = bool(d["enabled"])
        if "rotate" in d:
            r = int(d["rotate"]) % 360
            if r not in (0, 90, 180, 270):
                raise ValueError("rotate harus 0/90/180/270")
            kw["rotate"] = r
        if "flip" in d:
            f = str(d["flip"] or "none").lower()
            if f not in ("none", "h", "v"):
                raise ValueError("flip harus none/h/v")
            kw["flip"] = f
        if "brightness" in d:
            kw["brightness"] = _clamp(d["brightness"], -100, 100)
        if "contrast" in d:
            kw["contrast"] = _clamp(d["contrast"], 0.5, 2.0)
        if "saturation" in d:
            kw["saturation"] = _clamp(d["saturation"], 0.0, 2.0)
        if "gamma" in d:
            kw["gamma"] = _clamp(d["gamma"], 0.5, 2.5)
        if "clahe" in d:
            kw["clahe"] = bool(d["clahe"])
        if "clahe_clip" in d:
            kw["clahe_clip"] = _clamp(d["clahe_clip"], 0.5, 8.0)
        if "sharpen" in d:
            kw["sharpen"] = _clamp(d["sharpen"], 0.0, 1.0)
        if "denoise" in d:
            kw["denoise"] = bool(d["denoise"])
        if "roi" in d:
            roi = d["roi"]
            if roi in (None, "", [], "null"):
                kw["roi"] = None
            else:
                x, y, w, h = (float(v) for v in roi)
                x, y = min(max(x, 0.0), 0.95), min(max(y, 0.0), 0.95)
                w, h = min(max(w, 0.05), 1.0 - x), min(max(h, 0.05), 1.0 - y)
                kw["roi"] = (x, y, w, h)
        return replace(cfg, **kw)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["roi"] = list(self.roi) if self.roi else None
        return d

    @property
    def is_geometric_identity(self) -> bool:
        """True jika koordinat frame hasil = koordinat frame mentah (bbox bisa digambar di raw)."""
        return (not self.enabled) or (self.rotate == 0 and self.flip == "none" and self.roi is None)


_ROT = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}


class Preprocessor:
    def __init__(self, cfg: PreprocessConfig | None = None):
        self._cfg = cfg or PreprocessConfig()
        self._gamma_lut: tuple[float, np.ndarray] | None = None
        self._clahe: tuple[float, Any] | None = None

    @property
    def config(self) -> PreprocessConfig:
        return self._cfg

    def set_config(self, cfg: PreprocessConfig) -> None:
        self._cfg = cfg  # assignment referensi bersifat atomik di CPython

    def _lut(self, gamma: float) -> np.ndarray:
        if self._gamma_lut is None or self._gamma_lut[0] != gamma:
            inv = 1.0 / gamma
            table = ((np.arange(256) / 255.0) ** inv * 255.0).clip(0, 255).astype(np.uint8)
            self._gamma_lut = (gamma, table)
        return self._gamma_lut[1]

    def _clahe_obj(self, clip: float):
        if self._clahe is None or self._clahe[0] != clip:
            self._clahe = (clip, cv2.createCLAHE(clipLimit=clip, tileGridSize=(8, 8)))
        return self._clahe[1]

    def apply(self, img: np.ndarray) -> np.ndarray:
        c = self._cfg  # ambil sekali agar konsisten satu frame
        if not c.enabled:
            return img
        out = img
        if c.rotate:
            out = cv2.rotate(out, _ROT[c.rotate])
        if c.flip == "h":
            out = cv2.flip(out, 1)
        elif c.flip == "v":
            out = cv2.flip(out, 0)
        if c.roi:
            h, w = out.shape[:2]
            x, y, rw, rh = c.roi
            x0, y0 = int(x * w), int(y * h)
            x1, y1 = max(x0 + 2, int((x + rw) * w)), max(y0 + 2, int((y + rh) * h))
            out = out[y0:y1, x0:x1]
        if c.contrast != 1.0 or c.brightness != 0:
            out = cv2.convertScaleAbs(out, alpha=c.contrast, beta=c.brightness)
        if c.saturation != 1.0:
            hsv = cv2.cvtColor(out, cv2.COLOR_BGR2HSV)
            s = hsv[:, :, 1].astype(np.float32) * c.saturation
            hsv[:, :, 1] = np.clip(s, 0, 255).astype(np.uint8)
            out = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
        if c.gamma != 1.0:
            out = cv2.LUT(out, self._lut(c.gamma))
        if c.clahe:
            lab = cv2.cvtColor(out, cv2.COLOR_BGR2LAB)
            lab[:, :, 0] = self._clahe_obj(c.clahe_clip).apply(lab[:, :, 0])
            out = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
        if c.sharpen > 0:
            blur = cv2.GaussianBlur(out, (0, 0), 3)
            out = cv2.addWeighted(out, 1.0 + c.sharpen, blur, -c.sharpen, 0)
        if c.denoise:
            out = cv2.fastNlMeansDenoisingColored(out, None, 5, 5, 7, 21)
        if out is img:
            out = img.copy()
        return out
