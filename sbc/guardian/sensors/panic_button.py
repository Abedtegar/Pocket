"""Tombol panic fisik (GPIO pull-up ke GND). Prioritas tertinggi.

Berjalan di thread sendiri; saat tombol valid ditekan langsung memanggil callback
(EventEngine.trigger_panic_threadsafe) tanpa menunggu siklus lain.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

log = logging.getLogger(__name__)


class PanicButton(threading.Thread):
    def __init__(self, chip: str, line: int, debounce_ms: int, on_press: Callable[[], None]):
        super().__init__(name="panic_button", daemon=True)
        self.chip, self.line = chip, line
        self.debounce_s = max(0.005, debounce_ms / 1000.0)
        self.on_press = on_press
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        from ..hw_gpio import InputButton
        while not self._stop.is_set():
            try:
                btn = InputButton(self.chip, self.line)
            except Exception as e:
                log.error("panic button gagal dibuka (%s line %s): %s", self.chip, self.line, e)
                self._stop.wait(10)
                continue
            log.info("panic button siap di %s line %d", self.chip, self.line)
            try:
                while not self._stop.is_set():
                    if not btn.wait_edge(1.0):
                        continue
                    time.sleep(self.debounce_s)
                    if not btn.is_pressed():
                        continue  # pantulan/noise
                    log.warning("PANIC BUTTON ditekan")
                    try:
                        self.on_press()
                    except Exception:
                        log.exception("callback panic gagal")
                    # tunggu dilepas agar satu tekanan = satu event
                    while btn.is_pressed() and not self._stop.is_set():
                        time.sleep(0.05)
                    time.sleep(self.debounce_s)
            except Exception:
                log.exception("panic button error, membuka ulang")
            finally:
                try:
                    btn.close()
                except Exception:
                    pass
