# CLAUDE.md — Guardian pocket device

Rencana lengkap: `plan.md`. Isi folder:
- `sbc/` — program **pocket device** (Orange Pi Zero 2W, Python).
- `kamera esp32s3/` — **firmware kacamata** (PlatformIO, XIAO ESP32S3 Sense): hanya MJPEG `:81/stream` + MQTT
  (hr, status, LWT, camera/set/state, cmd). Build: `pio run`. Kontrak MQTT di `kamera esp32s3/README.md` harus
  tetap cocok dengan `sbc/guardian/sensors/mqtt_client.py` dan `sbc/guardian/vision/camera_presets.py`.

## Aturan
- Kerjakan per milestone (plan.md bagian 11). Keputusan di bagian 12 (K2–K14) **tanyakan ke user** dulu.
- Target runtime: Orange Pi OS (Linux, Python ≥ 3.10). Kode hardware (gpiod, smbus2, serial, aplay) hanya jalan di sana;
  tiap modul hardware punya `enabled` di `config.yaml`.
- Rahasia hanya di `sbc/.env` (gitignored). Nilai pin/bus bertanda `# VERIFIKASI` di `config.yaml` belum final (K3).
- Satu proses asyncio (`python -m guardian`); komponen blocking di thread, kirim ke loop via `Bus.publish_threadsafe`
  atau `loop.call_soon_threadsafe`. Vision selalu memproses frame terbaru.
- Event baru: tambah ke `SEVERITY`/`SOUNDS` di `guardian/engine/event_engine.py`, `TITLES` di `outputs/telegram.py`,
  `TYPE_LABEL` di `web/app.js`, dan cooldown di `config.yaml`.

## Peta kode (`sbc/guardian/`)
- `__main__.py` merakit semua komponen; `context.py` wadah komponen untuk API.
- `ingest/stream_reader.py` MJPEG ESP → frame terbaru. `vision/` preprocess (lapis 2), detector (ONNX/NCNN), temporal, pipeline, camera_presets (lapis 1 + preset).
- `sensors/` MQTT, GPS, panic button, INA219 power, netcheck. `hw_gpio.py` abstraksi libgpiod v1/v2.
- `engine/` rules (HR sustain, baterai, offline, GPS), zones, event_engine (cooldown, simpan, dispatch).
- `outputs/` telegram (+outbox), speaker (aplay prioritas), status_led (pola 7.1b).
- `storage/` SQLite (skema 6.5) + snapshot. `recorder.py` mode rekam dataset. `api/` FastAPI + WS.

## Perintah
```bash
cd sbc && .venv/bin/pytest -q              # unit test (tanpa hardware)
.venv/bin/python -m guardian               # jalankan
.venv/bin/python tools/fake_glasses.py     # simulator kacamata (MJPEG :8081 + MQTT)
.venv/bin/python tools/fake_gps.py         # simulator GPS (/tmp/fake_gps)
.venv/bin/python tools/bench_detector.py --model models/yolov5n.onnx
```
