# Guardian — program pocket device (Orange Pi Zero 2W)

Implementasi bagian SBC dari `../plan.md` (milestone M4–M7b): ingest kamera/MQTT/GPS/tombol/INA219,
pra-pemrosesan + YOLOv5n, event engine, SQLite, Telegram, speaker, LED status, website + PWA, mode rekam dataset.

## 1. Instalasi di Orange Pi
```bash
cd /home/orangepi/guardian/sbc
bash deploy/setup_pi.sh            # apt, venv, pip, mosquitto, suara, ikon, sudoers, systemd unit
.venv/bin/python tools/hash_password.py   # salin hasilnya ke .env
nano .env                          # TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, WEB_PASSWORD_HASH
```
Lalu **verifikasi** nilai bertanda `VERIFIKASI` di `config.yaml`:

| Item | Cara cek |
|---|---|
| `gps.port` | aktifkan overlay UART (`orangepi-config`/`/boot/orangepiEnv.txt`), `ls /dev/ttyS*`, `cat /dev/ttyS5` |
| `panic.gpio_chip`, `panic.line` | `gpioinfo`, pinout resmi Zero 2W |
| `status_led.lines` | `gpioinfo`; tiga offset R/G/B harus berbeda |
| `power.i2c_bus` | aktifkan overlay I2C, `ls /dev/i2c-*`, `i2cdetect -y <bus>` harus menemukan `40` |
| `speaker.device` | `aplay -l` → `plughw:<card>,0` |

Perangkat yang belum terpasang: set `enabled: false` di bagiannya (gps, panic, power, status_led, speaker, mqtt, vision).

## 2. Model
Lihat `models/README.md`. Tanpa model, sistem tetap jalan (stream + preprocess tampil), detektor nonaktif.

## 3. Menjalankan
```bash
.venv/bin/pytest -q                       # unit test
.venv/bin/python -m guardian              # manual (Ctrl+C untuk berhenti)
sudo systemctl enable --now guardian      # sebagai service
journalctl -u guardian -f
```
Web: `http://192.168.50.1:8000` (lokal AP) atau `https://<host>.<tailnet>.ts.net` setelah `sudo tailscale serve --bg 8000`
(PWA hanya bisa di-install lewat HTTPS Tailscale). Dokumentasi API: `/api/docs`.

## 4. Uji tanpa hardware kacamata
```bash
# terminal 1: kacamata palsu (MJPEG + MQTT); ketik h = HR tinggi, o = offline, s = stream mati
.venv/bin/python tools/fake_glasses.py --video contoh.mp4
# terminal 2: GPS palsu (lintasan melingkar), ketik x = fix hilang
.venv/bin/python tools/fake_gps.py --lat -7.28 --lon 112.79
# config.yaml: glasses.stream_url: http://127.0.0.1:8081/stream ; gps.port: /tmp/fake_gps
# terminal 3
.venv/bin/python -m guardian
```

| Event | Cara memicu |
|---|---|
| `panic` | tombol fisik, atau tab Pengaturan → Simulasikan event |
| `weapon` | model COCO + `classes: [knife]`, tunjukkan pisau / video berisi pisau |
| `hr_high` / `hr_low` | ketik `h` / `l` di fake_glasses (tunggu `sustain_s`) |
| `glasses_offline` | ketik `o` atau hentikan fake_glasses |
| `zone_enter` | buat zona di tab Zona yang memotong lintasan fake_gps |
| `gps_lost` | ketik `x` di fake_gps |
| `battery_low/critical` + shutdown | `PUT /api/settings {"power":{"fake_voltage":3.45}}` (shutdown jadi dry-run selama fake_voltage aktif) |
| outbox Telegram | cabut modem → picu event → pasang lagi → terkirim dalam ±30 s |

Cek MQTT: `mosquitto_sub -v -t 'glasses/#'`.

## 5. Rekam dataset (9A.7)
Tab **Kamera → Rekam dataset**. Hasil: `dataset_raw/S###_<tanggal>_<nama>/frames/*.jpg` + `meta.json`,
dan satu baris di `dataset_raw/dataset_log.csv`. Tanpa service: `tools/record_session.py` (hentikan service dulu,
karena ESP hanya melayani satu klien).

## 6. Catatan
- Parameter sensor dikirim ke ESP sebagai JSON: bool → `0/1`, `framesize` → nama (`"QVGA"`); firmware harus
  membalas `glasses/camera/state` (retained).
- Mosquitto hanya mendengar `127.0.0.1` dan `192.168.50.1`; jika AP belum aktif, hapus listener kedua sementara.
- Baterai: Li-ion 1S (`power.cells: 1`), kurva di `power.curve`. Isi `capacity_mah` untuk estimasi sisa waktu.
