"""Thread pembaca MJPEG dari ESP32. Hanya menyimpan frame JPEG terbaru.

ESP hanya melayani satu klien, jadi hanya thread ini yang menarik stream;
web menonton stream ulang dari SBC. Sambung ulang otomatis (mis. setelah framesize diganti).
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

import httpx

log = logging.getLogger(__name__)

SOI = b"\xff\xd8"
EOI = b"\xff\xd9"
MAX_BUFFER = 4 * 1024 * 1024


def extract_jpegs(buf: bytearray) -> list[bytes]:
    """Ambil semua JPEG lengkap dari buffer, sisakan potongan yang belum lengkap di buf."""
    frames: list[bytes] = []
    while True:
        s = buf.find(SOI)
        if s < 0:
            # simpan byte terakhir kalau-kalau 0xFF adalah awal SOI yang terpotong
            del buf[:-1]
            break
        e = buf.find(EOI, s + 2)
        if e < 0:
            if s > 0:
                del buf[:s]
            break
        frames.append(bytes(buf[s:e + 2]))
        del buf[:e + 2]
    return frames


class StreamReader(threading.Thread):
    def __init__(self, url: str, state, connect_timeout: float = 5.0, read_timeout: float = 5.0):
        super().__init__(name="stream_reader", daemon=True)
        self.url = url
        self.state = state
        self._timeout = httpx.Timeout(connect_timeout, read=read_timeout)
        self._stop = threading.Event()
        self._cond = threading.Condition()
        self._jpeg: bytes | None = None
        self._ts = 0.0
        self._seq = 0
        self._fps = 0.0
        self._callbacks: list[Callable[[bytes, float], None]] = []
        self._reconnect = threading.Event()

    # ---- API untuk konsumen ----
    def add_frame_callback(self, cb: Callable[[bytes, float], None]) -> None:
        self._callbacks.append(cb)

    def remove_frame_callback(self, cb: Callable[[bytes, float], None]) -> None:
        if cb in self._callbacks:
            self._callbacks.remove(cb)

    def latest(self) -> tuple[bytes | None, float, int]:
        with self._cond:
            return self._jpeg, self._ts, self._seq

    def wait_new(self, last_seq: int, timeout: float = 1.0) -> tuple[bytes | None, float, int]:
        with self._cond:
            if self._seq == last_seq:
                self._cond.wait(timeout)
            return self._jpeg, self._ts, self._seq

    def set_url(self, url: str) -> None:
        self.url = url
        self._reconnect.set()

    def reconnect(self) -> None:
        self._reconnect.set()

    def stop(self) -> None:
        self._stop.set()

    # ---- thread ----
    def _publish(self, jpeg: bytes) -> None:
        now = time.time()
        with self._cond:
            if self._ts:
                dt = now - self._ts
                if dt > 0:
                    inst = 1.0 / dt
                    self._fps = inst if self._fps == 0 else 0.9 * self._fps + 0.1 * inst
            self._jpeg = jpeg
            self._ts = now
            self._seq += 1
            self._cond.notify_all()
        self.state.update("stream", connected=True, last_frame=now, fps=round(self._fps, 1))
        for cb in list(self._callbacks):
            try:
                cb(jpeg, now)
            except Exception:
                log.exception("callback frame gagal")

    def run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            self._reconnect.clear()
            try:
                log.info("menyambung ke stream %s", self.url)
                with httpx.stream("GET", self.url, timeout=self._timeout) as r:
                    r.raise_for_status()
                    backoff = 1.0
                    buf = bytearray()
                    for chunk in r.iter_bytes():
                        if self._stop.is_set() or self._reconnect.is_set():
                            break
                        buf.extend(chunk)
                        for jpeg in extract_jpegs(buf):
                            self._publish(jpeg)
                        if len(buf) > MAX_BUFFER:
                            log.warning("buffer stream terlalu besar, direset")
                            buf.clear()
            except Exception as e:  # koneksi gagal / timeout / stream putus
                log.warning("stream terputus: %s", e)
            self.state.update("stream", connected=False, fps=0.0)
            self._fps = 0.0
            if self._stop.is_set():
                break
            if not self._reconnect.is_set():
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 10.0)
