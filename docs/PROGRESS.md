# Progres pengerjaan Guardian

Terakhir diperbarui: 27-11-2026. Dokumen ini adalah titik lanjut kerja. Mulai sekarang pengembangan `sbc/`
dilakukan langsung di Orange Pi lewat SSH. Rencana lengkap ada di `../plan.md`, aturan kerja di `../CLAUDE.md`.

---

## 1. Ringkasan status

| Bagian | Status | Teruji di mana |
|---|---|---|
| `sbc/` program pocket device (M4–M7b) | Kode lengkap | Orange Pi (Arch Linux ARM): 16 unit test lulus. `python -m guardian` dengan kacamata asli **belum dicoba** |
| `kamera esp32s3/` firmware kacamata (M1–M2) | Kode lengkap, fw 2.0.0 | **Terverifikasi 27-11-2026**: stream MJPEG tampil di browser, MQTT `online`/`hr`/`status`/`camera/state` diterima di Orange Pi |
| Model senjata (M8) | **Tahap 1 disiapkan**: `model/train.ipynb` (Colab) + `model/README.md`. Belum ada dataset/training | – |
| Jaringan (M3) | **Berubah dari plan**, lihat bagian 2 | **Berjalan**: Wi-Fi `SAFE`, mDNS `guardian.local` ↔ `guardian-glasses.local`, broker `0.0.0.0:1883` |

### Hasil uji integrasi ESP ↔ Orange Pi (27-11-2026)
- OS Orange Pi ternyata **Arch Linux ARM** (setup: `deploy/setup_arch.sh`, bukan `setup_pi.sh`). mDNS lewat
  **systemd-resolved** (avahi tidak dipakai). Hostname diganti `teen-pc` → `guardian`.
- Sensor kamera terdeteksi **OV3660** (bukan OV2640). `camera/state` cocok dengan `camera.sensor` di config.yaml, `errors` kosong.
- Stream 15–28 fps QVGA (target M1 ≥ 10 fps terpenuhi). RSSI −44..−49 dBm, baterai kacamata ~3.96 V.
- Heart rate: tanpa jari `ir` ≈ 1 000, menempel `ir` ≈ 101 000–103 000 (di bawah jenuh 250 000), bpm 77–96 stabil
  setelah ±10 s. Saat jari baru ditempel `ir` sempat 50 014 (tepat di ambang 50 000) → `finger` bisa berkedip sesaat.

### Milestone (plan.md bagian 11)
| # | Status |
|---|---|
| M0 Setup Orange Pi, SSH, Tailscale, venv, Mosquitto | **Sebagian**: SSH, venv, Mosquitto, hostname `guardian` selesai. Sisa: Tailscale, `.env` |
| M1 Firmware kamera MJPEG | **Selesai** (15–28 fps QVGA) |
| M2 Firmware MAX30102 + MQTT + LWT + tuning | **Sebagian**: hr/status/online/camera/state jalan. Sisa: uji `camera/set` (+ error), LWT saat daya dicabut |
| M3 Jaringan | Diganti: Wi-Fi modem + mDNS (bagian 2) |
| M4 Ingest + LED + simulator | Kode jadi; perlu verifikasi pin dan hardware |
| M5 Preprocess + YOLOv5n + benchmark | Kode jadi; perlu `yolov5n.onnx` COCO + `bench_detector.py` |
| M6 Event engine + Telegram + speaker + LED | Kode jadi; perlu `.env` Telegram dan uji tiap event |
| M7 Web + PWA | Kode jadi; uji via Tailscale HTTPS |
| M7b Rekam dataset | Kode jadi (tervalidasi di smoke test laptop) |
| M8 Model terlatih | Belum |
| M9 Integrasi + systemd + uji lapangan | Belum |

---

## 2. Keputusan yang menyimpang dari plan.md

| Topik | plan.md | Sekarang | Alasan |
|---|---|---|---|
| Jaringan lokal | Orange Pi jadi AP `guardian-ap`, subnet `192.168.50.0/24`, IP statis | **Wi-Fi bawaan modem USB 4G** (SSID `SAFE`). Orange Pi, kacamata, dan HP semua jadi klien modem. IP dari DHCP modem | Modem sudah memancarkan Wi-Fi; `wlan0` Orange Pi bebas |
| Penemuan alamat | IP statis | **mDNS**: Orange Pi = `guardian.local`, kacamata = `guardian-glasses.local` | IP DHCP berubah-ubah |
| Mosquitto | listener `127.0.0.1` + `192.168.50.1` | `listener 1883 0.0.0.0` (`sbc/deploy/mosquitto-guardian.conf`) | IP Orange Pi tidak tetap. Konsekuensi: broker tanpa password terbuka di Wi-Fi modem dan Tailscale |
| Pin baterai kacamata | A0 / GPIO1 | **GPIO4 (D3)**, divider 2×100k | Mengikuti wiring lama |
| Bagian 3 plan.md (`nmcli hotspot`) | Dipakai | **Tidak dipakai**; plan.md belum diperbarui | – |

### Keputusan terbuka yang sudah dijawab user
- K1: YOLOv5n 320.
- K2: ONNX Runtime default, NCNN opsional (`vision.backend`). Putuskan final setelah benchmark M5.
- K13 (27-11-2026): **satu kelas `senjata_tajam`** untuk training; labeling primer tetap rinci. `config.yaml`
  `vision.names/classes` sudah diset `[senjata_tajam]`.
- K14 (sebagian, 27-11-2026): **tahap 1 data publik** (Roboflow + negatif COCO) di **Google Colab**, data primer
  kacamata menyusul untuk fine-tune tahap 2. Target jumlah/jadwal 9A.5 dan 9A.11 belum ditetapkan.
- K10: baterai pocket device **Li-ion 1S** (`power.cells: 1`), kurva 4.20=100, 3.85=60, 3.70=30, 3.50=10, 3.30=0.

### Keputusan yang masih terbuka (tanyakan user sebelum memutuskan)
K3 pin UART/GPIO/I2C Orange Pi, K4 resolusi QVGA vs VGA, K5 ambang HR (sementara 120/45 bpm, sustain 10 s),
K6 klip video, K7 isi suara (sementara beep placeholder dari `tools/make_sounds.py`), K8 retensi (sementara 7 hari),
K9 rangkaian LED (sementara tabel 7.1b apa adanya), K11 posisi INA219, K12 preset kamera (hanya `default`),
K14 target jumlah data dan jadwal pengambilan data primer.

---

## 3. Isi repo (https://github.com/Abedtegar/Pocket)

```
plan.md                 rencana lengkap
CLAUDE.md               aturan kerja untuk Claude Code
docs/PROGRESS.md        dokumen ini
sbc/                    program pocket device (Python) -> DIKERJAKAN DI ORANGE PI
  guardian/             paket utama (python -m guardian)
  web/                  website + PWA
  tools/                fake_glasses, fake_gps, bench_detector, record_session, make_sounds, make_icons, hash_password
  deploy/               setup_pi.sh, mosquitto-guardian.conf, guardian-shutdown.sudoers
  systemd/              guardian.service
  tests/                pytest (tanpa hardware)
kamera esp32s3/         firmware kacamata (PlatformIO) -> TETAP DIKERJAKAN DI LAPTOP (butuh USB ke board)
```

Berkas yang **tidak ada di git** dan harus dibuat manual:
- `sbc/.env`: `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`, `WEB_PASSWORD_HASH` (dari `tools/hash_password.py`), `SESSION_SECRET`. Template: `sbc/.env.example`.
- `kamera esp32s3/include/secrets.h`: hanya di laptop. Template: `secrets.example.h`.
- `sbc/models/*.onnx`, `sbc/sounds/*.wav`, `sbc/web/icons/*.png` (dibuat oleh `setup_pi.sh`), `sbc/data/`, `sbc/dataset_raw/`.

---

## 4. Langkah berikutnya (urutan disarankan, di Orange Pi)

### 4.1 Verifikasi kamera tanpa Orange Pi (laptop, bisa kapan saja)
Laptop tersambung ke Wi-Fi `SAFE`, buka `http://guardian-glasses.local:81/stream`, atau IP dari baris serial
`[wifi] stream: http://...`. Pesan `[mqtt] gagal connect` di serial normal selama broker belum ada.
Sebelumnya stream timeout karena `STATIC_IP 192.168.50.10` tidak cocok dengan subnet modem. Sekarang sudah DHCP
(`STATIC_IP ""`), perlu **upload ulang** firmware terbaru (dengan mDNS).

### 4.2 Setup Orange Pi (M0) — sudah dijalankan; OS ternyata Arch, pakai `deploy/setup_arch.sh`
```bash
git clone https://github.com/Abedtegar/Pocket.git ~/guardian    # path dipakai systemd/guardian.service
cd ~/guardian/sbc
bash deploy/setup_pi.sh        # apt (mosquitto, avahi, libnss-mdns, ...), hostname -> guardian, venv, suara, ikon, sudoers, unit systemd
.venv/bin/python tools/hash_password.py   # salin hasil ke .env
nano .env
.venv/bin/pytest -q            # harus 16 passed
```
Cek: `ping guardian-glasses.local` dari Orange Pi, dan `mosquitto_sub -v -t 'glasses/#'` harus menerima `glasses/hr` tiap detik.
Kalau `.local` tidak terselesaikan (modem memblokir multicast), pakai IP: `MQTT_HOST` di secrets.h dan `glasses.stream_url` di config.yaml.

Tailscale (akses jarak jauh + HTTPS untuk PWA):
```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
sudo tailscale serve --bg 8000
```

### 4.3 Verifikasi hardware dan isi nilai `# VERIFIKASI` di `sbc/config.yaml` (K3, tanyakan user)
| Item | Cara cek |
|---|---|
| `gps.port` | aktifkan overlay UART, `ls /dev/ttyS*`, `cat /dev/ttyS5` |
| `panic.gpio_chip`, `panic.line` | `gpioinfo`, pinout resmi Zero 2W |
| `status_led.lines` (r/g/b berbeda) | `gpioinfo` |
| `power.i2c_bus` | aktifkan overlay I2C, `i2cdetect -y <bus>` → `40` |
| `speaker.device` | `aplay -l` → `plughw:<card>,0` |
Modul yang belum terpasang: set `enabled: false`.

### 4.4 Model untuk uji pipeline (M5)
Ekspor `yolov5n.pt` COCO → ONNX 320 di PC/Colab (`sbc/models/README.md`), salin ke `sbc/models/yolov5n.onnx`,
set `vision.model` dan `classes: [knife]`, lalu `.venv/bin/python tools/bench_detector.py --model models/yolov5n.onnx`.
Catat FPS dan latensi per tahap, lalu putuskan K2 dan K4 bersama user.

### 4.5 Jalankan dan uji event (M6–M7)
`.venv/bin/python -m guardian`, buka `http://guardian.local:8000`. Cara memicu tiap event ada di `sbc/README.md` §4.
Setelah stabil: `sudo systemctl enable --now guardian`.

---

## 5. Catatan penting / jebakan yang sudah diketahui

- **Keamanan**: firmware lama (`config.h`) menyimpan API key OpenRouter `sk-or-v1-…`. File itu sudah dihapus dan
  tidak pernah masuk git, tapi key harus di-**rotate** di dashboard OpenRouter.
- ESP hanya melayani **satu klien stream**: koneksi baru menggantikan yang lama. Jangan buka stream ESP di browser
  saat `guardian` berjalan; tonton lewat web SBC (`/api/stream`).
- Ganti `framesize` memutus stream ESP sebentar; `stream_reader` menyambung ulang otomatis.
- PubSubClient (ESP) hanya publish QoS0; `online`/`camera/state` tetap retained, LWT QoS1, keepalive 10 s.
- Kontrak MQTT ESP ↔ SBC: boolean dikirim `0/1`, `framesize` berupa nama (`"QVGA"`). Didokumentasikan di
  `kamera esp32s3/README.md`. Jaga tetap cocok dengan `sbc/guardian/sensors/mqtt_client.py` dan `vision/camera_presets.py`.
- `power.fake_voltage` (uji baterai tanpa INA219) membuat shutdown hanya **dry-run**.
- Jika `WEB_PASSWORD_HASH` kosong, web **tanpa login**. Isi sebelum dipakai di lapangan.
- `hw_gpio.py` mendukung libgpiod Python v2 (`pip install gpiod`) dan v1 (`python3-libgpiod`). Kode hardware
  (gpiod, INA219, GPS UART, aplay) belum pernah dijalankan di perangkat asli, jadi bug di sana paling mungkin muncul.
- Diagnostik clang di VS Code untuk firmware ("Arduino.h not found") bukan error build; yang menentukan `pio run`.
