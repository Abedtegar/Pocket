"""Wadah semua komponen yang sedang berjalan, dibagikan ke API."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AppContext:
    cfg: Any
    state: Any
    bus: Any
    db: Any
    snapshots: Any
    reader: Any = None
    pipeline: Any = None
    preprocessor: Any = None
    detector: Any = None
    camera: Any = None
    mqtt: Any = None
    engine: Any = None
    rules: Any = None
    telegram: Any = None
    speaker: Any = None
    led: Any = None
    recorder: Any = None
    power: Any = None
    extra: dict = field(default_factory=dict)
