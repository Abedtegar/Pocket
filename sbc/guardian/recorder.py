"""Mode rekam dataset (plan.md 9A.7).

Menyimpan frame MENTAH dari ESP32 (sebelum preprocess lapis 2) sebagai JPEG berurutan,
plus meta.json dan satu baris di dataset_log.csv.
"""
from __future__ import annotations

import csv
import json
import logging
import re
import threading
import time
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

LOG_FIELDS = ["session_id", "tanggal", "lokasi", "cahaya", "jarak", "gerak", "benda", "relawan_id",
              "preset", "durasi_s", "jumlah_frame", "catatan"]


def _slug(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", text.strip().lower()).strip("_")
    return s[:40] or "sesi"


class DatasetRecorder:
    def __init__(self, root: Path, log_csv: Path, state, tz):
        self.root = root
        self.log_csv = log_csv
        self.state = state
        self.tz = tz
        self._lock = threading.Lock()
        self.active = False
        self.session_dir: Path | None = None
        self.meta: dict = {}
        self.frames = 0
        self.t_start = 0.0
        self.t_last = 0.0

    def _next_id(self) -> str:
        self.root.mkdir(parents=True, exist_ok=True)
        nums = [int(m.group(1)) for d in self.root.iterdir()
                if d.is_dir() and (m := re.match(r"S(\d+)_", d.name))]
        return f"S{(max(nums) + 1) if nums else 1:03d}"

    def start(self, info: dict, extra_meta: dict) -> dict:
        with self._lock:
            if self.active:
                raise RuntimeError("perekaman sedang berjalan")
            now = datetime.now(self.tz)
            sid = self._next_id()
            name = "_".join(_slug(str(info[k])) for k in ("cahaya", "lokasi") if info.get(k)) or "sesi"
            if info.get("nama"):
                name = _slug(info["nama"])
            self.session_dir = self.root / f"{sid}_{now:%Y-%m-%d}_{name}"
            (self.session_dir / "frames").mkdir(parents=True)
            self.meta = {"session_id": sid, "start": now.isoformat(timespec="seconds"),
                         "info": info, **extra_meta}
            self.frames = 0
            self.t_start = time.time()
            self.t_last = 0.0
            self.active = True
        self.state.update("recorder", active=True, session=self.session_dir.name, frames=0, fps=0.0)
        log.info("rekam dataset dimulai: %s", self.session_dir)
        return self.status()

    def on_frame(self, jpeg: bytes, ts: float) -> None:
        """Callback dari thread stream_reader."""
        if not self.active:
            return
        with self._lock:
            if not self.active or self.session_dir is None:
                return
            self.frames += 1
            (self.session_dir / "frames" / f"{self.frames:06d}.jpg").write_bytes(jpeg)
            self.t_last = ts
            n = self.frames
        if n % 15 == 0:
            self.state.update("recorder", frames=n, fps=self._fps())

    def _fps(self) -> float:
        dur = (self.t_last or time.time()) - self.t_start
        return round(self.frames / dur, 2) if dur > 0 else 0.0

    def stop(self, end_meta: dict | None = None) -> dict:
        with self._lock:
            if not self.active:
                raise RuntimeError("tidak ada perekaman aktif")
            self.active = False
            duration = round(time.time() - self.t_start, 1)
            fps = self._fps()
            self.meta.update({"end": datetime.now(self.tz).isoformat(timespec="seconds"),
                              "duration_s": duration, "frames": self.frames, "fps": fps,
                              **(end_meta or {})})
            (self.session_dir / "meta.json").write_text(json.dumps(self.meta, indent=2, ensure_ascii=False),
                                                       encoding="utf-8")
            info = self.meta.get("info", {})
            row = {
                "session_id": self.meta["session_id"], "tanggal": self.meta["start"][:10],
                "lokasi": info.get("lokasi", ""), "cahaya": info.get("cahaya", ""),
                "jarak": info.get("jarak", ""), "gerak": info.get("gerak", ""), "benda": info.get("benda", ""),
                "relawan_id": info.get("relawan_id", ""), "preset": self.meta.get("preset_name", ""),
                "durasi_s": duration, "jumlah_frame": self.frames, "catatan": info.get("catatan", ""),
            }
            self.log_csv.parent.mkdir(parents=True, exist_ok=True)
            new = not self.log_csv.exists()
            with open(self.log_csv, "a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=LOG_FIELDS)
                if new:
                    w.writeheader()
                w.writerow(row)
            result = {"session": self.session_dir.name, "frames": self.frames, "duration_s": duration, "fps": fps}
        self.state.update("recorder", active=False, frames=self.frames, fps=fps)
        log.info("rekam dataset selesai: %s", result)
        return result

    def status(self) -> dict:
        return {"active": self.active, "session": self.session_dir.name if self.session_dir else None,
                "frames": self.frames, "fps": self._fps() if self.active else self.state.value("recorder", "fps"),
                "elapsed_s": round(time.time() - self.t_start, 1) if self.active else 0}
