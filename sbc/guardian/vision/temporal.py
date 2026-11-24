"""Filter temporal N dari M frame untuk meredam false positive."""
from __future__ import annotations

from collections import deque


class TemporalFilter:
    def __init__(self, n: int, m: int):
        self.n = max(1, int(n))
        self.m = max(self.n, int(m))
        self._hits: deque[dict | None] = deque(maxlen=self.m)

    def reset(self) -> None:
        self._hits.clear()

    def update(self, dets: list[dict], classes: set[str], conf: float) -> tuple[bool, dict | None]:
        """Tambahkan hasil satu frame. Return (lolos, deteksi terbaik di frame ini atau terakhir)."""
        cands = [d for d in dets if (not classes or d["label"] in classes) and d["conf"] >= conf]
        best = max(cands, key=lambda d: d["conf"]) if cands else None
        self._hits.append(best)
        hits = [h for h in self._hits if h is not None]
        if len(hits) >= self.n:
            return True, best or hits[-1]
        return False, best
