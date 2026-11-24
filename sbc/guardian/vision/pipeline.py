"""Thread vision: frame terbaru -> decode -> preprocess -> YOLO -> NMS -> temporal.

Selalu memproses frame TERBARU (bukan antrean) agar latensi tidak menumpuk.
Menyimpan JPEG beranotasi (raw & processed) untuk /api/stream dan snapshot event.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

import cv2
import numpy as np

from .detector import Detector, draw_detections
from .preprocess import Preprocessor
from .temporal import TemporalFilter

log = logging.getLogger(__name__)


class VisionPipeline(threading.Thread):
    def __init__(self, cfg, state, reader, preprocessor: Preprocessor, detector: Detector | None,
                 on_trigger: Callable[[dict, bytes], None]):
        super().__init__(name="vision", daemon=True)
        self.cfg = cfg
        self.state = state
        self.reader = reader
        self.pre = preprocessor
        self.detector = detector
        self.on_trigger = on_trigger
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._cond = threading.Condition()
        self._raw_jpeg: bytes | None = None
        self._proc_jpeg: bytes | None = None
        self._out_seq = 0
        self._temporal = TemporalFilter(cfg.get("vision.temporal_n", 3), cfg.get("vision.temporal_m", 5))
        self._fps = 0.0
        self._last_done = 0.0

    # ---- kontrol ----
    def stop(self) -> None:
        self._stop.set()

    def pause(self, paused: bool) -> None:
        if paused:
            self._paused.set()
        else:
            self._paused.clear()
            self._temporal.reset()
        self.state.update("vision", paused=paused)

    @property
    def paused(self) -> bool:
        return self._paused.is_set()

    def latest(self, view: str = "processed") -> tuple[bytes | None, int]:
        with self._cond:
            return (self._proc_jpeg if view == "processed" else self._raw_jpeg), self._out_seq

    def _store(self, raw: bytes | None, proc: bytes | None) -> None:
        with self._cond:
            self._raw_jpeg, self._proc_jpeg = raw, proc
            self._out_seq += 1
            self._cond.notify_all()

    # ---- loop ----
    def run(self) -> None:
        last_seq = -1
        last_t = 0.0
        while not self._stop.is_set():
            jpeg, ts, seq = self.reader.wait_new(last_seq, timeout=1.0)
            if jpeg is None or seq == last_seq:
                continue
            max_fps = float(self.cfg.get("vision.max_fps", 5) or 5)
            wait = (1.0 / max_fps) - (time.perf_counter() - last_t)
            if wait > 0:
                if self._stop.wait(wait):
                    break
                jpeg, ts, seq = self.reader.latest()
            last_seq = seq
            last_t = time.perf_counter()
            if self._paused.is_set():
                # saat merekam dataset: tidak decode/deteksi, cukup teruskan JPEG mentah untuk pratinjau
                self._store(jpeg, jpeg)
                continue
            try:
                self._process(jpeg)
            except Exception as e:
                log.exception("pipeline gagal memproses frame")
                self.state.update("vision", error=str(e))

    def _process(self, jpeg: bytes) -> None:
        t0 = time.perf_counter()
        img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return
        t1 = time.perf_counter()
        proc = self.pre.apply(img)
        t2 = time.perf_counter()
        lat = {"decode": (t1 - t0) * 1000, "preprocess": (t2 - t1) * 1000}
        dets: list[dict] = []
        targets = set(self.cfg.get("vision.classes", []) or [])
        if self.detector is not None and self.cfg.get("vision.enabled", True):
            conf = float(self.cfg.get("vision.conf", 0.45))
            iou = float(self.cfg.get("vision.iou", 0.45))
            dets, t = self.detector.detect(proc, conf, iou)
            lat.update(t)
            n, m = int(self.cfg.get("vision.temporal_n", 3)), int(self.cfg.get("vision.temporal_m", 5))
            if (n, m) != (self._temporal.n, self._temporal.m):
                self._temporal = TemporalFilter(n, m)
            passed, best = self._temporal.update(dets, targets, conf)
        else:
            passed, best = False, None
        t3 = time.perf_counter()
        lat["total"] = (t3 - t0) * 1000

        # anotasi
        proc_vis = draw_detections(proc.copy(), dets, targets) if dets else proc
        ok, proc_buf = cv2.imencode(".jpg", proc_vis, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if dets and self.pre.config.is_geometric_identity:
            raw_vis = draw_detections(img.copy(), dets, targets)
            _, raw_buf = cv2.imencode(".jpg", raw_vis, [cv2.IMWRITE_JPEG_QUALITY, 80])
            raw_bytes = raw_buf.tobytes()
        else:
            raw_bytes = jpeg
        proc_bytes = proc_buf.tobytes() if ok else None
        self._store(raw_bytes, proc_bytes)

        now = time.time()
        if self._last_done:
            inst = 1.0 / max(1e-3, now - self._last_done)
            self._fps = inst if self._fps == 0 else 0.8 * self._fps + 0.2 * inst
        self._last_done = now
        self.state.update("vision", fps=round(self._fps, 2),
                          latency_ms={k: round(v, 1) for k, v in lat.items()},
                          detections=dets[:10], error=None)
        if passed and best is not None and proc_bytes:
            self.on_trigger(best, proc_bytes)
