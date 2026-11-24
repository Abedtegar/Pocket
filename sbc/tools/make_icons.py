"""Buat ikon PNG PWA (192 & 512) dengan OpenCV. Jalankan sekali: python tools/make_icons.py"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

OUT = Path(__file__).resolve().parent.parent / "web" / "icons"


def draw(size: int) -> np.ndarray:
    s = size / 512.0
    img = np.zeros((size, size, 3), np.uint8)
    img[:] = (28, 23, 20)  # BGR #14171c
    shield = np.array([[256, 72], [408, 132], [408, 248], [380, 340], [256, 444], [132, 340], [104, 248], [104, 132]])
    cv2.fillPoly(img, [(shield * s).astype(np.int32)], (246, 130, 59), cv2.LINE_AA)
    t = max(2, int(20 * s))
    for cx in (200, 312):
        cv2.circle(img, (int(cx * s), int(250 * s)), int(44 * s), (255, 255, 255), t, cv2.LINE_AA)
    cv2.line(img, (int(244 * s), int(250 * s)), (int(268 * s), int(250 * s)), (255, 255, 255), t, cv2.LINE_AA)
    return img


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for size in (192, 512):
        cv2.imwrite(str(OUT / f"icon-{size}.png"), draw(size))
        print("dibuat", OUT / f"icon-{size}.png")
