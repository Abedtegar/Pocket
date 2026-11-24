"""Pemutar suara arahan lewat aplay dengan antrean prioritas.

Suara berprioritas lebih tinggi (mis. panic) menyela suara yang sedang diputar.
"""
from __future__ import annotations

import itertools
import logging
import queue
import subprocess
import threading
from pathlib import Path

log = logging.getLogger(__name__)


class Speaker(threading.Thread):
    def __init__(self, device: str, sounds_dir: Path, enabled: bool = True):
        super().__init__(name="speaker", daemon=True)
        self.device = device
        self.sounds_dir = sounds_dir
        self.enabled = enabled
        self._q: queue.PriorityQueue = queue.PriorityQueue(maxsize=20)
        self._seq = itertools.count()
        self._proc: subprocess.Popen | None = None
        self._cur_priority = -1
        self._lock = threading.Lock()
        self._stop = threading.Event()

    def play(self, name: str, priority: int = 1) -> None:
        if not self.enabled:
            log.info("speaker nonaktif, lewati %s", name)
            return
        path = self.sounds_dir / name
        if not path.exists():
            log.warning("file suara tidak ada: %s (jalankan tools/make_sounds.py)", path)
            return
        try:
            self._q.put_nowait((-priority, next(self._seq), str(path), priority))
        except queue.Full:
            log.warning("antrean speaker penuh, %s dibuang", name)
            return
        with self._lock:
            if self._proc and self._proc.poll() is None and priority > self._cur_priority:
                self._proc.terminate()  # sela suara yang lebih rendah

    def stop(self) -> None:
        self._stop.set()
        self._q.put((-99, next(self._seq), "", 99))
        with self._lock:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()

    def run(self) -> None:
        while not self._stop.is_set():
            _, _, path, prio = self._q.get()
            if self._stop.is_set() or not path:
                break
            try:
                with self._lock:
                    self._proc = subprocess.Popen(["aplay", "-q", "-D", self.device, path],
                                                  stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                    self._cur_priority = prio
                _, err = self._proc.communicate(timeout=60)
                if self._proc.returncode not in (0, -15) and err:
                    log.warning("aplay error: %s", err.decode(errors="ignore").strip())
            except subprocess.TimeoutExpired:
                self._proc.kill()
            except FileNotFoundError:
                log.error("aplay tidak ditemukan (sudo apt install alsa-utils)")
                self.enabled = False
            except Exception:
                log.exception("gagal memutar %s", path)
            finally:
                self._cur_priority = -1
