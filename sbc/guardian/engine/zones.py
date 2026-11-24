"""Zona rawan berbentuk lingkaran (titik + radius) dan deteksi transisi luar -> dalam."""
from __future__ import annotations

import math

EARTH_R = 6371000.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(a))


class ZoneTracker:
    def __init__(self) -> None:
        self.zones: list[dict] = []
        self._inside: dict[int, bool] = {}

    def set_zones(self, zones: list[dict]) -> None:
        self.zones = [z for z in zones if z.get("active", True)]
        ids = {z["id"] for z in self.zones}
        self._inside = {k: v for k, v in self._inside.items() if k in ids}

    def update(self, lat: float, lon: float) -> list[dict]:
        """Return daftar zona yang baru dimasuki (termasuk saat fix pertama sudah di dalam)."""
        entered = []
        for z in self.zones:
            d = haversine_m(lat, lon, z["lat"], z["lon"])
            inside = d <= float(z["radius_m"])
            # histeresis 10% radius agar tidak bolak-balik di tepi
            if self._inside.get(z["id"]) and not inside and d <= float(z["radius_m"]) * 1.1:
                inside = True
            was = self._inside.get(z["id"], False)
            if inside and not was:
                entered.append({**z, "distance_m": round(d, 1)})
            self._inside[z["id"]] = inside
        return entered

    def inside(self) -> list[int]:
        return [k for k, v in self._inside.items() if v]
