"""LED RGB status (common anode, aktif LOW) dengan pola sesuai plan.md 7.1b."""
from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger(__name__)

COLORS = {
    "off": (0, 0, 0), "red": (1, 0, 0), "green": (0, 1, 0), "blue": (0, 0, 1),
    "yellow": (1, 1, 0), "purple": (1, 0, 1), "cyan": (0, 1, 1), "white": (1, 1, 1),
}
# pola: (periode detik, durasi menyala detik); None = menyala tetap
PATTERNS = {
    "solid": None,
    "fast": (0.25, 0.125),        # 4 Hz
    "slow": (1.0, 0.5),           # 1 Hz
    "blink2": (0.5, 0.25),        # 2 Hz
    "heartbeat": (3.0, 0.08),     # kedip singkat tiap 3 s
}


def decide(st: dict, cfg) -> tuple[str, str]:
    """Pilih (warna, pola) berdasarkan prioritas tabel 7.1b."""
    if st["alarm"].get("active"):
        return "red", "fast"
    level = st["power"].get("level")
    if level == "critical":
        return "red", "solid"
    if level == "low":
        return "purple", "slow"
    if not st["glasses"].get("online"):
        return "blue", "slow"
    gps_bad = cfg.get("gps.enabled", True) and not st["gps"].get("fix")
    if not st["net"].get("internet") or gps_bad:
        return "yellow", "solid"
    return "green", "heartbeat"


class StatusLed(threading.Thread):
    def __init__(self, cfg, state):
        super().__init__(name="status_led", daemon=True)
        self.cfg = cfg
        self.state = state
        self.out = None
        self._stop = threading.Event()
        self._booting = True
        self._test_until = 0.0
        led = cfg.section("status_led")
        if led.get("enabled", True):
            try:
                from ..hw_gpio import OutputLines
                self.out = OutputLines(led.get("gpio_chip", "gpiochip0"), dict(led.get("lines", {})),
                                       bool(led.get("active_low", True)), consumer="guardian-led")
            except Exception as e:
                log.error("LED status gagal dibuka: %s", e)

    def ready(self) -> None:
        self._booting = False

    def test_cycle(self) -> None:
        """Uji LED: R, G, B, kuning, ungu, putih masing-masing 1 detik."""
        self._test_until = time.time() + 6.0

    def stop(self) -> None:
        self._stop.set()

    def _set(self, color: str, on: bool) -> None:
        r, g, b = COLORS[color] if on else (0, 0, 0)
        if self.out:
            try:
                self.out.set({"r": bool(r), "g": bool(g), "b": bool(b)})
            except Exception as e:
                log.error("LED gagal di-set: %s", e)
                self.out = None

    def run(self) -> None:
        last_shown = None
        color, pattern = "white", "blink2"
        next_decide = 0.0
        while not self._stop.is_set():
            now = time.time()
            if now < self._test_until:
                seq = ["red", "green", "blue", "yellow", "purple", "white"]
                color, pattern = seq[min(5, int(6 - (self._test_until - now)))], "solid"
            elif self._booting:
                color, pattern = "white", "blink2"
            elif now >= next_decide:
                color, pattern = decide(self.state.snapshot(), self.cfg)
                next_decide = now + 0.25
            p = PATTERNS[pattern]
            on = True if p is None else (now % p[0]) < p[1]
            self._set(color, on)
            if (color, pattern) != last_shown:
                self.state.update("led", color=color, pattern=pattern)
                last_shown = (color, pattern)
            self._stop.wait(0.025)
        self._set("off", False)
        if self.out:
            self.out.close()
