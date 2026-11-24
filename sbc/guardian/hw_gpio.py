"""Abstraksi GPIO di atas libgpiod (mendukung binding Python v2 dan v1).

- v2: `pip install gpiod` (>=2.x), API `gpiod.request_lines`.
- v1: paket apt `python3-libgpiod` (1.x), API `chip.get_line(...).request(...)`.
"""
from __future__ import annotations

from datetime import timedelta

import gpiod

V2 = hasattr(gpiod, "request_lines")


def chip_path(name: str) -> str:
    return name if name.startswith("/dev/") else f"/dev/{name}"


class OutputLines:
    """Beberapa line output bernama, mis. {'r': 6, 'g': 7, 'b': 8}."""

    def __init__(self, chip: str, lines: dict[str, int], active_low: bool, consumer: str = "guardian"):
        self.lines = dict(lines)
        offsets = list(self.lines.values())
        if len(set(offsets)) != len(offsets):
            raise ValueError(f"offset GPIO duplikat: {self.lines} (isi status_led.lines dengan benar)")
        if V2:
            from gpiod.line import Direction, Value
            self._Value = Value
            settings = gpiod.LineSettings(direction=Direction.OUTPUT, active_low=active_low,
                                          output_value=Value.INACTIVE)
            self._req = gpiod.request_lines(chip_path(chip), consumer=consumer,
                                            config={tuple(offsets): settings})
        else:
            self._chip = gpiod.Chip(chip_path(chip))
            self._bulk = self._chip.get_lines(offsets)
            flags = gpiod.LINE_REQ_FLAG_ACTIVE_LOW if active_low else 0
            self._bulk.request(consumer=consumer, type=gpiod.LINE_REQ_DIR_OUT, flags=flags,
                               default_vals=[0] * len(offsets))

    def set(self, values: dict[str, bool]) -> None:
        """values: nama -> True (aktif/menyala) / False."""
        if V2:
            V = self._Value
            self._req.set_values({self.lines[n]: (V.ACTIVE if on else V.INACTIVE)
                                  for n, on in values.items() if n in self.lines})
        else:
            names = list(self.lines.keys())
            current = self._bulk.get_values()
            new = [int(values.get(n, bool(current[i]))) for i, n in enumerate(names)]
            self._bulk.set_values(new)

    def close(self) -> None:
        try:
            self.set({n: False for n in self.lines})
        except Exception:
            pass
        if V2:
            self._req.release()
        else:
            self._bulk.release()
            self._chip.close()


class InputButton:
    """Tombol ke GND dengan pull-up internal; ditekan = level LOW."""

    def __init__(self, chip: str, line: int, consumer: str = "guardian-panic"):
        self.offset = line
        if V2:
            from gpiod.line import Bias, Direction, Edge, Value
            self._Value = Value
            settings = gpiod.LineSettings(direction=Direction.INPUT, bias=Bias.PULL_UP,
                                          edge_detection=Edge.FALLING)
            self._req = gpiod.request_lines(chip_path(chip), consumer=consumer, config={line: settings})
        else:
            self._chip = gpiod.Chip(chip_path(chip))
            self._line = self._chip.get_line(line)
            flags = getattr(gpiod, "LINE_REQ_FLAG_BIAS_PULL_UP", 0)
            self._line.request(consumer=consumer, type=gpiod.LINE_REQ_EV_FALLING_EDGE, flags=flags)

    def wait_edge(self, timeout_s: float) -> bool:
        """Tunggu falling edge. True jika ada edge (event dibaca habis)."""
        if V2:
            if self._req.wait_edge_events(timedelta(seconds=timeout_s)):
                self._req.read_edge_events()
                return True
            return False
        if self._line.event_wait(sec=int(timeout_s), nsec=int((timeout_s % 1) * 1e9)):
            self._line.event_read()
            return True
        return False

    def is_pressed(self) -> bool:
        if V2:
            return self._req.get_value(self.offset) == self._Value.INACTIVE
        return self._line.get_value() == 0

    def close(self) -> None:
        if V2:
            self._req.release()
        else:
            self._line.release()
            self._chip.close()
