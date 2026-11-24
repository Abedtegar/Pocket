"""Penyimpanan JPEG kejadian + retensi.

File: <snapshot_dir>/YYYY-MM-DD/HHMMSS_<id>.jpg
Nilai di DB/event: "snapshots/YYYY-MM-DD/HHMMSS_<id>.jpg" (disajikan di URL /snapshots/...).
"""
from __future__ import annotations

import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)


class SnapshotStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, jpeg: bytes, ev_id: str, when: datetime) -> str:
        day = when.strftime("%Y-%m-%d")
        name = f"{when.strftime('%H%M%S')}_{ev_id}.jpg"
        folder = self.root / day
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(jpeg)
        return f"snapshots/{day}/{name}"

    def resolve(self, rel: str) -> Path | None:
        """Ubah path relatif (dengan/tanpa prefix 'snapshots/') ke file, cegah path traversal."""
        rel = rel.removeprefix("snapshots/")
        p = (self.root / rel).resolve()
        if self.root.resolve() not in p.parents or not p.is_file():
            return None
        return p

    def purge(self, days: int, today: datetime) -> int:
        cutoff = (today - timedelta(days=days)).strftime("%Y-%m-%d")
        removed = 0
        for d in self.root.iterdir():
            if d.is_dir() and len(d.name) == 10 and d.name < cutoff:
                shutil.rmtree(d, ignore_errors=True)
                removed += 1
        if removed:
            log.info("retensi: %d folder snapshot dihapus", removed)
        return removed
