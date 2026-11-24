"""Entry point: python -m guardian

Menyalakan semua komponen dalam satu proses asyncio; komponen blocking/CPU-bound
(stream, vision, GPS, tombol panic, LED, speaker) berjalan di thread sendiri.
"""
from __future__ import annotations

import asyncio
import logging
import signal
import sys

import uvicorn

from .bus import Bus
from .config import load_config
from .context import AppContext
from .engine.event_engine import EventEngine
from .engine.rules import RuleRunner
from .ingest.stream_reader import StreamReader
from .outputs.speaker import Speaker
from .outputs.status_led import StatusLed
from .outputs.telegram import Telegram
from .recorder import DatasetRecorder
from .sensors import netcheck
from .state import State
from .storage.db import Database
from .storage.snapshots import SnapshotStore
from .vision.camera_presets import CameraManager
from .vision.pipeline import VisionPipeline
from .vision.preprocess import PreprocessConfig, Preprocessor

log = logging.getLogger("guardian")


async def retention_task(ctx: AppContext) -> None:
    while True:
        days = int(ctx.cfg.get("storage.retention_days", 7))
        try:
            await asyncio.to_thread(ctx.snapshots.purge, days, ctx.cfg.now())
            await ctx.db.purge_samples(days)
        except Exception:
            log.exception("retensi gagal")
        await asyncio.sleep(6 * 3600)


async def status_log_task(ctx: AppContext) -> None:
    """Ringkasan berkala di log (kriteria M4: fps, bpm, koordinat, V/A/W)."""
    while True:
        await asyncio.sleep(10)
        st = ctx.state.snapshot()
        p, g, h, v = st["power"], st["gps"], st["hr"], st["vision"]
        log.info("stream %.1f fps | vision %.1f fps | bpm %s%s | gps %s | batt %s V %s A %s W %s%% | net %s | led %s",
                 st["stream"]["fps"], v["fps"], h["bpm"], "" if h["finger"] else " (no finger)",
                 f"{g['lat']},{g['lon']} sats={g['sats']}" if g["fix"] else "no-fix",
                 p["voltage"], p["current_a"], p["power_w"], p["pct"],
                 "ok" if st["net"]["internet"] else "down", st["led"]["color"])


async def amain() -> None:
    cfg = load_config()
    logging.basicConfig(level=getattr(logging, str(cfg.get("logging.level", "INFO")).upper(), logging.INFO),
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    loop = asyncio.get_running_loop()
    bus = Bus()
    bus.bind(loop)
    state = State()

    # ---- storage + pengaturan dari web ----
    db = Database(cfg.path(cfg.get("storage.db", "data/guardian.db")), cfg.tz)
    await db.init()
    overrides = await db.get_setting("config_overrides", {})
    if overrides:
        cfg.merge(cfg.validate_overrides(overrides))
        log.info("pengaturan dari web dimuat: %s", list(overrides))
    snapshots = SnapshotStore(cfg.path(cfg.get("storage.snapshot_dir", "data/snapshots")))
    ctx = AppContext(cfg=cfg, state=state, bus=bus, db=db, snapshots=snapshots)
    tasks: list[asyncio.Task] = []

    # ---- output ----
    ctx.led = StatusLed(cfg, state)
    ctx.led.start()
    ctx.speaker = Speaker(cfg.get("speaker.device", "default"), cfg.path(cfg.get("speaker.sounds_dir", "sounds")),
                          enabled=bool(cfg.get("speaker.enabled", True)))
    ctx.speaker.start()
    ctx.telegram = Telegram(cfg, db, snapshots)

    # ---- kamera + vision ----
    ctx.reader = StreamReader(cfg.get("glasses.stream_url"), state)
    ctx.reader.start()
    ctx.preprocessor = Preprocessor(PreprocessConfig.from_dict(cfg.get("camera.preprocess", {})))
    if cfg.get("vision.enabled", True):
        try:
            from .vision.detector import Detector
            ctx.detector = Detector(cfg.section("vision"), cfg.base_dir)
            state.update("vision", enabled=True, model_ok=True)
        except Exception as e:
            log.error("detector tidak aktif: %s", e)
            state.update("vision", enabled=True, model_ok=False, error=str(e))

    def frame_source():
        jpeg, _, _ = ctx.reader.latest()
        return jpeg

    ctx.engine = EventEngine(cfg, state, bus, db, snapshots, ctx.telegram, ctx.speaker, frame_source)
    ctx.pipeline = VisionPipeline(cfg, state, ctx.reader, ctx.preprocessor, ctx.detector,
                                  ctx.engine.on_detection_threadsafe)
    ctx.pipeline.start()

    # ---- MQTT + preset kamera ----
    if cfg.get("mqtt.enabled", True):
        from .sensors.mqtt_client import MqttLink
        ctx.mqtt = MqttLink(cfg, state, bus)
        ctx.mqtt.start()
    ctx.camera = CameraManager(cfg, db, ctx.preprocessor, ctx.mqtt, ctx.reader)
    await ctx.camera.load()

    def on_glasses_online(online: bool) -> None:
        if online:
            ctx.camera.resend_sensor()
    bus.on("glasses_online", on_glasses_online)

    def on_camera_state(data) -> None:
        # framesize berubah -> stream ESP restart; sambung ulang cepat
        if isinstance(data, dict) and data.get("framesize"):
            prev = ctx.extra.get("framesize")
            if prev is not None and prev != data["framesize"]:
                ctx.reader.reconnect()
            ctx.extra["framesize"] = data["framesize"]
    bus.on("camera_state", on_camera_state)

    # ---- sensor lain ----
    if cfg.get("gps.enabled", True):
        from .sensors.gps import GpsReader
        state.update("gps", enabled=True)
        gps = GpsReader(cfg.get("gps.port"), int(cfg.get("gps.baud", 9600)), state)
        gps.start()
    if cfg.get("panic.enabled", True):
        from .sensors.panic_button import PanicButton
        PanicButton(cfg.get("panic.gpio_chip", "gpiochip0"), int(cfg.get("panic.line", 0)),
                    int(cfg.get("panic.debounce_ms", 50)), ctx.engine.trigger_panic_threadsafe).start()
    if cfg.get("power.enabled", True) or cfg.get("power.fake_voltage") is not None:
        from .sensors.power import PowerMonitor
        ctx.power = PowerMonitor(cfg, state, bus)
        tasks.append(asyncio.create_task(ctx.power.run(), name="power"))

    # ---- aturan + tugas berkala ----
    ctx.rules = RuleRunner(cfg, state, bus, ctx.engine, db)
    await ctx.rules.start()
    await ctx.engine.refresh_alarm()
    tasks += [
        asyncio.create_task(ctx.rules.periodic(), name="rules"),
        asyncio.create_task(netcheck.run(cfg, state, bus), name="netcheck"),
        asyncio.create_task(ctx.telegram.outbox_worker(bus), name="outbox"),
        asyncio.create_task(retention_task(ctx), name="retention"),
        asyncio.create_task(status_log_task(ctx), name="status_log"),
    ]

    ctx.recorder = DatasetRecorder(cfg.path(cfg.get("recorder.dir", "dataset_raw")),
                                   cfg.path(cfg.get("recorder.log_csv", "dataset_raw/dataset_log.csv")),
                                   state, cfg.tz)

    # ---- API ----
    from .api.main import create_app
    app = create_app(ctx)
    server = uvicorn.Server(uvicorn.Config(app, host=cfg.get("api.host", "0.0.0.0"),
                                           port=int(cfg.get("api.port", 8000)), log_level="warning",
                                           proxy_headers=True, forwarded_allow_ips="*"))
    server.install_signal_handlers = lambda: None  # uvicorn lama: sinyal ditangani di sini

    def request_stop(*_):
        log.info("berhenti...")
        server.should_exit = True
    # signal.signal (bukan loop.add_signal_handler) agar uvicorn baru yang me-raise ulang
    # sinyal setelah serve() tetap memanggil handler ini, bukan default (yang membunuh proses)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, request_stop)

    ctx.led.ready()
    log.info("Guardian berjalan di http://%s:%s", cfg.get("api.host"), cfg.get("api.port"))
    try:
        await server.serve()
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if ctx.recorder.active:
            ctx.recorder.stop()
        ctx.pipeline.stop()
        ctx.reader.stop()
        if ctx.mqtt:
            ctx.mqtt.stop()
        ctx.speaker.stop()
        ctx.led.stop()
        await ctx.telegram.close()
        if db.conn:
            await db.close()
        log.info("selesai")


def main() -> None:
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
