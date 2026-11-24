"""Buat WAV placeholder untuk tiap event di sounds/ (ganti dengan rekaman suara arahan, lihat K7).

    python tools/make_sounds.py
"""
from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

RATE = 22050
OUT = Path(__file__).resolve().parent.parent / "sounds"


def tone(freq: float, dur: float, vol: float = 0.6) -> list[float]:
    n = int(RATE * dur)
    fade = int(RATE * 0.01)
    out = []
    for i in range(n):
        env = min(1.0, i / fade, (n - i) / fade)
        out.append(vol * env * math.sin(2 * math.pi * freq * i / RATE))
    return out


def silence(dur: float) -> list[float]:
    return [0.0] * int(RATE * dur)


def sweep(f0: float, f1: float, dur: float, vol: float = 0.6) -> list[float]:
    n = int(RATE * dur)
    out, phase = [], 0.0
    for i in range(n):
        f = f0 + (f1 - f0) * i / n
        phase += 2 * math.pi * f / RATE
        out.append(vol * math.sin(phase))
    return out


def write(name: str, samples: list[float]) -> None:
    OUT.mkdir(exist_ok=True)
    with wave.open(str(OUT / name), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1, min(1, s)) * 32767)) for s in samples))
    print("dibuat", OUT / name)


def main() -> None:
    write("panic.wav", sum((sweep(600, 1200, 0.4) + sweep(1200, 600, 0.4) for _ in range(4)), []))
    write("weapon.wav", sum((tone(1000, 0.18) + silence(0.08) for _ in range(5)), []))
    write("hr.wav", sum((tone(700, 0.25) + silence(0.15) for _ in range(2)), []))
    write("zone.wav", tone(600, 0.7))
    write("offline.wav", tone(880, 0.25) + tone(660, 0.25) + tone(440, 0.4))
    write("battery.wav", tone(400, 0.15) + silence(0.1) + tone(400, 0.15))
    write("test.wav", tone(880, 0.3))


if __name__ == "__main__":
    main()
