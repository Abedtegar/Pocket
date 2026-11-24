"""Notifikasi Telegram Bot ke orang tua, dengan outbox untuk saat internet mati (plan.md 7.3)."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import httpx

log = logging.getLogger(__name__)

TITLES = {
    "panic": "⚠️ [PANIC] Tombol darurat ditekan",
    "weapon": "⚠️ [SENJATA] Terdeteksi senjata tajam",
    "hr_high": "❤️ [DETAK JANTUNG] Terlalu tinggi",
    "hr_low": "❤️ [DETAK JANTUNG] Terlalu rendah",
    "zone_enter": "📍 [ZONA RAWAN] Memasuki zona rawan",
    "glasses_offline": "📴 [KACAMATA] Kacamata terputus",
    "battery_low": "🔋 [BATERAI] Baterai pocket device rendah",
    "battery_critical": "🪫 [BATERAI] Baterai pocket device kritis",
    "gps_lost": "🛰️ [GPS] Sinyal GPS hilang",
    "test": "✅ [UJI] Pesan uji Guardian",
}
LOC_SRC = {"gps": "GPS", "last_known": "lokasi terakhir", "none": "tidak ada"}


def format_message(ev: dict, now_tz) -> str:
    title = TITLES.get(ev["type"], f"[{ev['type']}]")
    try:
        t = datetime.fromisoformat(ev["ts"]).strftime("%d-%m-%Y %H:%M:%S")
    except (ValueError, TypeError):
        t = str(ev.get("ts"))
    data = ev.get("data") or {}
    lines = [title, f"Waktu: {t}"]
    if ev["type"] == "weapon" and data.get("label"):
        lines.append(f"Objek: {data['label']} ({float(data.get('conf', 0)) * 100:.0f}%)")
    if ev["type"] == "zone_enter" and data.get("zone"):
        lines.append(f"Zona: {data['zone']} (radius {data.get('radius_m')} m)")
    if ev["type"] in ("battery_low", "battery_critical") and data.get("pct") is not None:
        lines.append(f"Baterai: {data['pct']}% ({data.get('voltage', 0):.2f} V)")
    if ev["type"] == "glasses_offline" and data.get("reason"):
        lines.append(f"Penyebab: {data['reason']}")
    if ev.get("lat") is not None:
        age = data.get("loc_age_s")
        age_txt = f", {age} dtk lalu" if age is not None else ""
        lines.append(f"Lokasi: https://maps.google.com/?q={ev['lat']:.4f},{ev['lon']:.4f} "
                     f"({LOC_SRC.get(ev.get('loc_src'), ev.get('loc_src'))}{age_txt})")
    else:
        lines.append("Lokasi: tidak tersedia")
    if data.get("bpm"):
        lines.append(f"Detak jantung: {data['bpm']} bpm")
    return "\n".join(lines)


class Telegram:
    def __init__(self, cfg, db, snapshots):
        self.cfg = cfg
        self.db = db
        self.snapshots = snapshots
        self.token = cfg.env["TELEGRAM_TOKEN"]
        self.chat_id = cfg.env["TELEGRAM_CHAT_ID"]
        self.enabled = bool(cfg.get("telegram.enabled", True) and self.token and self.chat_id)
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=8.0))
        self._lock = asyncio.Lock()
        if not self.enabled:
            log.warning("Telegram nonaktif (cek telegram.enabled, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID)")

    @property
    def base(self) -> str:
        return f"https://api.telegram.org/bot{self.token}"

    async def _call(self, method: str, data: dict, files: dict | None = None) -> dict:
        r = await self.client.post(f"{self.base}/{method}", data=data, files=files)
        body = r.json()
        if not body.get("ok"):
            raise RuntimeError(f"Telegram {method} gagal: {body.get('description')}")
        return body

    async def send_text(self, text: str) -> None:
        await self._call("sendMessage", {"chat_id": self.chat_id, "text": text,
                                         "disable_web_page_preview": "true"})

    async def _send_event(self, ev: dict) -> None:
        text = format_message(ev, self.cfg.tz)
        path = self.snapshots.resolve(ev["snapshot"]) if ev.get("snapshot") else None
        if path is not None:
            with open(path, "rb") as f:
                await self._call("sendPhoto", {"chat_id": self.chat_id, "caption": text[:1024]},
                                 files={"photo": (path.name, f.read(), "image/jpeg")})
        else:
            await self.send_text(text)
        if ev.get("lat") is not None and ev["type"] in ("panic", "weapon", "hr_high", "hr_low",
                                                         "battery_critical", "zone_enter"):
            await self._call("sendLocation", {"chat_id": self.chat_id, "latitude": ev["lat"],
                                              "longitude": ev["lon"]})

    async def notify(self, ev: dict) -> bool:
        """Kirim event; gagal -> masuk outbox. Return True jika terkirim."""
        try:
            async with self._lock:
                await self._send_event(ev)
            return True
        except Exception as e:
            log.warning("Telegram gagal, masuk outbox: %s", e)
            await self.db.outbox_add(self.cfg.now_iso(), {"event": ev})
            return False

    async def outbox_worker(self, bus=None) -> None:
        while True:
            await asyncio.sleep(float(self.cfg.get("telegram.retry_interval_s", 30)))
            if not self.enabled:
                continue
            try:
                rows = await self.db.outbox_list()
            except Exception:
                continue
            for row in rows:
                ev = row["payload"].get("event")
                try:
                    async with self._lock:
                        if ev:
                            await self._send_event(ev)
                        else:
                            await self.send_text(row["payload"].get("text", ""))
                except Exception as e:
                    log.info("outbox belum terkirim (%s)", e)
                    await self.db.outbox_fail(row["id"])
                    break  # internet kemungkinan masih mati
                await self.db.outbox_delete(row["id"])
                if ev:
                    await self.db.mark_notified(ev["id"])
                    if bus:
                        bus.publish("event_update", {"id": ev["id"], "notified": True})
                log.info("outbox terkirim: %s", ev["type"] if ev else "teks")

    async def close(self) -> None:
        await self.client.aclose()
