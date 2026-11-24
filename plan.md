# plan.md — Sistem Deteksi Bahaya: Kacamata ESP32-S3 + Pocket Device Orange Pi

Dokumen ini adalah rencana kerja yang bisa dieksekusi bertahap oleh Claude Code di VS Code:
- **Firmware kacamata** → PlatformIO (XIAO ESP32-S3 Sense)
- **Program pocket device** → Python di Orange Pi Zero 2W via Remote-SSH
- **Website** → disajikan oleh SBC, diakses lokal dan jarak jauh via Tailscale

> Untuk Claude Code: kerjakan per milestone (bagian 11). Jangan lompat milestone. Setiap milestone punya kriteria lulus. Bagian 12 berisi keputusan yang **belum final** — tanyakan ke user sebelum mengambil keputusan di sana.

---

## 0. Keputusan yang sudah final

| Topik | Keputusan |
|---|---|
| Firmware ESP32 | Mulai baru, ringan. ESP hanya streaming kamera + kirim heart rate. Semua logika di SBC |
| Transport kamera | MJPEG over HTTP (TCP), ESP sebagai server, SBC menarik stream |
| Transport sensor | MQTT (Mosquitto di SBC) |
| Jaringan lokal | Orange Pi menjadi Wi-Fi AP; kacamata dan HP terhubung ke AP |
| Internet | Modem USB stick 4G di Orange Pi |
| GPS | Modul VK2828U7G5LF (u-blox 7, NMEA via UART) di Orange Pi |
| SBC | Orange Pi Zero 2W RAM 2 GB, Orange Pi OS resmi (Debian/Ubuntu) |
| Deteksi visual v1 | Senjata tajam saja. Perkelahian ditunda |
| Model | **YOLOv5n**, input 320×320, dilatih dari dataset publik (repo `ultralytics/yolov5`) |
| Tuning kamera | Dua lapis, diatur dari web: (1) parameter sensor di ESP32, (2) pra-pemrosesan OpenCV di SBC sebelum YOLO |
| Heart rate | Memicu alarm sendiri berdasarkan ambang (dengan debounce, lihat 7.2) |
| Zona rawan | Diinput manual di web (lingkaran titik + radius) |
| Backend | Python: FastAPI + vanilla JS, database SQLite lokal di SBC |
| Akses jarak jauh | Tailscale (HTTPS valid, PWA bisa di-install) |
| Notifikasi | Telegram Bot ke orang tua |
| Audio | USB sound card (DIINAMI G16) → amplifier (PAM8403) → speaker |
| Panic button | Tombol fisik di pocket device (GPIO Orange Pi) |
| Monitoring baterai pocket device | INA219 (I2C) — tegangan, arus, daya baterai |
| Indikator kondisi | LED RGB common anode, 3 pin GPIO (aktif LOW) |

---

## 1. Gambaran sistem

```
┌──────────── Kacamata (XIAO ESP32-S3 Sense) ────────────┐
│ OV2640/OV3660 ──► HTTP MJPEG server :81/stream          │
│ MAX30102 (I2C) ──► MQTT publish  glasses/hr            │
│ status/battery  ──► MQTT publish  glasses/status       │
└───────────────────────────┬─────────────────────────────┘
                            │ Wi-Fi (AP milik Orange Pi)
┌───────────────────────────▼──── Pocket device (Orange Pi Zero 2W) ─────┐
│ stream_reader ─► detector (YOLO) ─► temporal filter ─┐                  │
│ mqtt_client (hr, status, LWT) ───────────────────────┼─► event_engine   │
│ gps (UART, NMEA) ────────────────────────────────────┤      │           │
│ panic_button (GPIO, prioritas tertinggi) ────────────┘      │           │
│                                                             ▼           │
│        SQLite ◄──── storage      speaker (aplay)    telegram (antrean)  │
│        FastAPI (REST + WebSocket + MJPEG beranotasi) ──► web statis     │
└──────────────┬──────────────────────────────────────┬──────────────────┘
               │ Wi-Fi AP (lokal)                     │ modem USB 4G
          HP pemakai                         Tailscale ─► HP orang tua
                                             Telegram API
```

---

## 2. Hardware dan wiring

### 2.1 Kacamata

| Komponen | Koneksi XIAO ESP32-S3 Sense | Catatan |
|---|---|---|
| Kamera (board Sense) | Konektor bawaan | Pin kamera lihat 5.3 |
| MAX30102 | SDA = D4 (GPIO5), SCL = D5 (GPIO6), 3V3, GND | Alamat I2C 0x57 |
| Baterai LiPo | Pad BAT+ / BAT− XIAO + switch | XIAO punya charger bawaan |
| Pembacaan baterai (opsional) | Pembagi tegangan 2×100k ke A0 (GPIO1) | XIAO tidak punya pembacaan baterai bawaan |

### 2.2 Pocket device

| Komponen | Koneksi Orange Pi Zero 2W | Catatan |
|---|---|---|
| Hub USB-C (wajib) | Port USB-C data | Board hanya punya 1 port USB data |
| Modem USB stick 4G | Hub | Muncul sebagai antarmuka ethernet (HiLink) |
| USB sound card DIINAMI | Hub | Muncul sebagai kartu ALSA |
| PAM8403 + speaker | Jack 3.5 mm sound card, VCC 5V | Ground bersama dengan 5V sistem |
| GPS VK2828U7G5LF | UART di header 40-pin, VCC 3.3–5V, GND | 9600 baud NMEA default. **Pin UART: verifikasi dengan manual resmi Zero 2W + aktifkan overlay UART** |
| Panic button | 1 GPIO (pull-up) + GND | Debounce di software |
| Baterai + switch + regulator 5V | Port USB-C daya | Regulator minimal 5V 3A (modem 4G punya arus puncak tinggi) |
| INA219 | I2C di header 40-pin (SDA, SCL), VCC 3.3V, GND | Alamat default 0x40. Shunt dipasang **seri di sisi baterai, sebelum regulator 5V** (VIN+ dari baterai, VIN− ke regulator) |
| LED RGB common anode | Anoda ke 3.3V; katoda R, G, B masing-masing lewat resistor ke 3 GPIO | GPIO LOW = LED menyala. Resistor lihat catatan di bawah |

> ⚠️ Verifikasi pinout UART, I2C, dan GPIO di manual resmi Orange Pi Zero 2W sebelum menyolder. Jangan memakai pin UART debug. Aktifkan overlay I2C yang sesuai.

**Catatan INA219**
- Tegangan bus maksimal 26V, cukup untuk baterai 1S–4S.
- Modul umum memakai shunt 0.1 Ω → arus terukur maksimal ±3.2 A. Modem 4G + SBC + amplifier bisa mendekati batas ini saat puncak. Pastikan konfigurasi kalibrasi (`32V_2A` atau custom) sesuai arus nyata, atau ganti shunt.
- Ground INA219, baterai, dan Orange Pi harus bersama.

**Catatan LED common anode di 3.3V**
- Merah (Vf ≈ 2.0V): resistor ±220 Ω → ±6 mA.
- Hijau dan biru (Vf ≈ 2.8–3.2V): sisa tegangan hanya 0.1–0.5V dari 3.3V, sehingga LED bisa redup atau tidak menyala. Pakai resistor kecil (33–68 Ω) dan uji, atau pindahkan anoda ke 5V dengan driver transistor NPN/N-MOSFET di sisi katoda (lihat K9).
- **Jangan** menyambungkan anoda ke 5V lalu katoda langsung ke GPIO 3.3V: GPIO tidak bisa mematikan LED sepenuhnya dan pin bisa menerima tegangan di atas 3.3V.
- Arus per GPIO dijaga ≤ 8 mA.

---

## 3. Jaringan

| Item | Nilai default |
|---|---|
| SSID AP | `guardian-ap` (password di `secrets`) |
| Subnet | `192.168.50.0/24` |
| IP Orange Pi (wlan0) | `192.168.50.1` |
| IP kacamata | DHCP reservation `192.168.50.10` (atau statis di firmware) |
| Internet | Modem USB (biasanya `usb0`/`eth1`, gateway `192.168.8.1`) |
| Mode AP | NetworkManager hotspot mode `shared` (NAT otomatis, HP pemakai ikut dapat internet untuk peta) |
| Port | MQTT 1883 (hanya wlan0), API/web 8000, MJPEG ESP 81 |

Langkah setup (jalankan via SSH, sesuaikan nama interface):
```bash
nmcli dev wifi hotspot ifname wlan0 con-name guardian-ap ssid guardian-ap password '<PASSWORD>'
nmcli con modify guardian-ap ipv4.addresses 192.168.50.1/24 ipv4.method shared
nmcli con modify guardian-ap connection.autoconnect yes
nmcli con up guardian-ap
```
Catatan: setelah wlan0 menjadi AP, SSH ke Orange Pi dilakukan lewat Wi-Fi AP tersebut atau lewat Tailscale. Siapkan akses Tailscale **sebelum** mengubah wlan0 menjadi AP agar tidak terkunci.

Tailscale:
```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
sudo tailscale serve --bg 8000   # HTTPS https://<host>.<tailnet>.ts.net
```

---

## 4. Protokol data

### 4.1 Video
- ESP: `GET http://192.168.50.10:81/stream` → `multipart/x-mixed-replace` MJPEG
- ESP: `GET /capture` → satu JPEG (untuk uji)
- Default: QVGA 320×240 atau VGA 640×480, JPEG quality 12, target 10–15 fps
- Hanya **satu klien** (SBC) yang menarik stream ESP. Web menonton stream ulang dari SBC.

### 4.2 Topik MQTT

| Topik | Arah | Payload (JSON) | QoS |
|---|---|---|---|
| `glasses/hr` | ESP → SBC | `{"bpm":82,"finger":true,"ir":51234,"ts":123456}` setiap 1 s | 0 |
| `glasses/status` | ESP → SBC | `{"batt_mv":3920,"rssi":-58,"uptime":3600,"heap":123000,"cam_ok":true}` setiap 10 s | 0 |
| `glasses/online` | ESP → SBC | `"1"` saat connect, LWT `"0"` (retained) | 1 |
| `glasses/cmd` | SBC → ESP | `{"stream":true}` | 1 |
| `glasses/camera/set` | SBC → ESP | Parameter sensor (lihat 5.6), boleh sebagian: `{"brightness":1,"saturation":-1}` | 1 |
| `glasses/camera/state` | ESP → SBC | Seluruh parameter sensor yang sedang aktif, dikirim saat connect dan setelah setiap `set` (retained) | 1 |

`ts` adalah `millis()` ESP. Waktu acuan tetap waktu SBC saat pesan diterima.

### 4.3 Event internal (SBC)
```json
{
  "id": "uuid",
  "ts": "2026-11-22T09:30:00+07:00",
  "type": "weapon | hr_high | hr_low | zone_enter | panic | glasses_offline | gps_lost | battery_low | battery_critical",
  "severity": 1,
  "data": {"label": "knife", "conf": 0.71, "bpm": 135},
  "lat": -7.28, "lon": 112.79, "loc_src": "gps | last_known | none",
  "snapshot": "snapshots/2026-11-22/093000_uuid.jpg",
  "notified": true
}
```
Severity: 3 = panic, 2 = weapon / hr / glasses_offline / battery_critical, 1 = zone_enter / gps_lost / battery_low.

---

## 5. Firmware kacamata (PlatformIO)

### 5.1 Struktur
```
firmware/
├── platformio.ini
├── include/
│   ├── config.h          # konstanta, pin, interval
│   └── secrets.h         # SSID, password, IP broker (gitignored)
├── include/secrets.example.h
└── src/
    ├── main.cpp
    ├── camera_server.cpp/.h   # init kamera + HTTP MJPEG
    ├── heart_rate.cpp/.h      # MAX30102 + algoritma bpm
    ├── mqtt_link.cpp/.h       # koneksi, publish, LWT, cmd
    ├── camera_tuning.cpp/.h   # terapkan & simpan parameter sensor (NVS)
    └── battery.cpp/.h         # opsional
```

### 5.2 platformio.ini (titik awal, verifikasi saat build)
```ini
[env:xiao_esp32s3]
platform = espressif32
board = seeed_xiao_esp32s3
framework = arduino
monitor_speed = 115200
board_build.arduino.memory_type = qio_opi
build_flags =
  -DBOARD_HAS_PSRAM
  -DCORE_DEBUG_LEVEL=1
lib_deps =
  knolleary/PubSubClient
  sparkfun/SparkFun MAX3010x Pulse and Proximity Sensor Library
  bblanchon/ArduinoJson
```

### 5.3 Pin kamera XIAO ESP32-S3 Sense
```
PWDN=-1 RESET=-1 XCLK=10 SIOD=40 SIOC=39
Y9=48 Y8=11 Y7=12 Y6=14 Y5=16 Y4=18 Y3=17 Y2=15
VSYNC=38 HREF=47 PCLK=13
```
Gunakan `fb_count = 2`, `fb_location = CAMERA_FB_IN_PSRAM`, `grab_mode = CAMERA_GRAB_LATEST`.

### 5.4 Pembagian task
| Task | Core | Isi |
|---|---|---|
| HTTP server MJPEG (`esp_http_server`) | 1 | Kirim frame terbaru |
| `hrTask` | 0 | Baca MAX30102 ~100 Hz, hitung bpm, publish 1 Hz |
| `netTask` | 0 | Jaga Wi-Fi + MQTT, reconnect dengan backoff, publish status 10 s, terima `glasses/cmd` |

### 5.5 Aturan firmware
- Tidak ada `delay()` panjang di loop. Pakai FreeRTOS task.
- Reconnect Wi-Fi dan MQTT otomatis. Kamera tetap jalan saat MQTT putus.
- Deteksi jari: jika IR < ambang (mis. 50000), kirim `finger:false` dan `bpm:0`.
- Rata-rata bpm 4–8 detak terakhir; buang nilai di luar 30–220 bpm.
- `secrets.h` tidak masuk git.

### 5.6 Tuning parameter sensor kamera (lapis 1, di ESP32)
Diterapkan langsung ke sensor lewat `sensor_t` (`esp_camera_sensor_get()`), sehingga tidak menambah beban CPU di SBC.

| Parameter | Rentang | Default | Fungsi |
|---|---|---|---|
| `framesize` | QQVGA, QVGA, CIF, VGA, SVGA | QVGA | Resolusi |
| `quality` | 4–63 (kecil = lebih bagus) | 12 | Kompresi JPEG |
| `brightness` | −2…2 | 0 | Kecerahan |
| `contrast` | −2…2 | 0 | Kontras |
| `saturation` | −2…2 | 0 | Saturasi |
| `sharpness` | −2…2 | 0 | Ketajaman (tidak semua sensor mendukung) |
| `awb` / `wb_mode` | on/off, 0–4 | on / 0 (auto) | White balance (auto, sunny, cloudy, office, home) |
| `aec` / `aec_value` / `ae_level` | on/off, 0–1200, −2…2 | on / 300 / 0 | Eksposur otomatis atau manual |
| `agc` / `agc_gain` / `gainceiling` | on/off, 0–30, 0–6 | on / 0 / 2 | Gain otomatis atau manual (pengaruh noise saat gelap) |
| `hmirror` / `vflip` | 0/1 | 0 / 0 | Orientasi sesuai posisi kamera di kacamata |
| `lenc`, `bpc`, `wpc`, `raw_gma`, `dcw` | 0/1 | 1,0,1,1,1 | Koreksi lensa, piksel rusak, gamma, downsize |

Aturan:
- Pesan `glasses/camera/set` boleh berisi sebagian parameter. Nilai di luar rentang ditolak dan dilaporkan di `glasses/camera/state`.
- Parameter disimpan di NVS (`Preferences`) agar bertahan setelah reboot.
- Saat `glasses/online = 1`, SBC mengirim ulang preset aktif agar ESP dan SBC selalu sinkron.
- Ganti `framesize` memerlukan jeda singkat pada stream; SBC harus menyambung ulang stream otomatis.
- Nama parameter dan rentang di atas mengikuti driver `esp32-camera` untuk OV2640. Jika modul memakai OV3660/OV5640, verifikasi rentangnya.

> Catatan sensor: PPG di kacamata (pelipis/batang kacamata) sangat sensitif terhadap gerakan dan tekanan kontak. Uji penempatan sensor lebih dulu (M1) sebelum menyetel ambang alarm.

---

## 6. Program SBC (Python)

### 6.1 Struktur
```
sbc/
├── pyproject.toml / requirements.txt
├── config.yaml                 # ambang, URL, port (tanpa rahasia)
├── .env                        # TELEGRAM_TOKEN, CHAT_ID, WEB_PASSWORD_HASH (gitignored)
├── guardian/
│   ├── __main__.py             # entry point, menyalakan semua komponen
│   ├── config.py
│   ├── bus.py                  # asyncio.Queue / pub-sub internal
│   ├── ingest/
│   │   └── stream_reader.py    # thread: baca MJPEG, simpan frame terbaru saja
│   ├── vision/
│   │   ├── preprocess.py       # pipeline OpenCV yang bisa diatur (lapis 2)
│   │   ├── camera_presets.py   # simpan/muat preset gabungan sensor + preprocess
│   │   ├── detector.py         # YOLOv5n via ONNX Runtime / NCNN, letterbox, NMS
│   │   └── temporal.py         # N dari M frame
│   ├── sensors/
│   │   ├── mqtt_client.py      # paho-mqtt: hr, status, online
│   │   ├── gps.py              # pyserial + pynmea2
│   │   ├── panic_button.py     # gpiod, debounce
│   │   └── power.py            # INA219 via smbus2: V, I, P, estimasi % baterai
│   ├── engine/
│   │   ├── rules.py            # aturan per jenis event
│   │   ├── zones.py            # haversine, cek masuk zona
│   │   └── event_engine.py     # cooldown, severity, dispatch
│   ├── outputs/
│   │   ├── telegram.py         # antrean + retry saat offline
│   │   ├── speaker.py          # antrean prioritas, aplay
│   │   └── status_led.py       # LED RGB: state machine pola warna/kedip
│   ├── storage/
│   │   ├── db.py               # SQLite (aiosqlite)
│   │   └── snapshots.py        # simpan JPEG kejadian, retensi
│   └── api/
│       ├── main.py             # FastAPI app
│       ├── routes.py           # REST
│       ├── ws.py               # WebSocket live
│       └── auth.py             # login sederhana (cookie session)
├── web/                        # statis, disajikan FastAPI
│   ├── index.html  app.js  style.css
│   ├── manifest.webmanifest  sw.js  icons/
├── sounds/                     # WAV arahan: weapon.wav, panic.wav, hr.wav, zone.wav, offline.wav
├── models/                     # weapon.onnx / weapon_ncnn_model/
├── tools/
│   ├── fake_glasses.py         # simulator: MJPEG dari file video + publish MQTT palsu
│   ├── fake_gps.py             # simulator NMEA lewat pty
│   └── bench_detector.py       # ukur FPS & latensi model di Orange Pi
├── systemd/guardian.service
└── tests/
```

### 6.2 Dependensi utama
`fastapi`, `uvicorn`, `paho-mqtt`, `aiosqlite`, `pyserial`, `pynmea2`, `gpiod`, `smbus2`, `opencv-python-headless`, `numpy`, `onnxruntime` (atau `ncnn`), `httpx`, `python-dotenv`, `pyyaml`, `passlib[bcrypt]`.
Paket sistem: `mosquitto`, `alsa-utils`, `python3-venv`, `ffmpeg` (opsional).

### 6.3 Model konkurensi
- Satu proses `guardian` dengan `asyncio`.
- `stream_reader` dan `detector` berjalan di thread terpisah (CPU-bound / blocking I/O), mengirim hasil ke `bus` lewat `loop.call_soon_threadsafe`.
- `panic_button` di thread sendiri, langsung memanggil `event_engine.trigger_panic()` tanpa menunggu siklus lain.
- Urutan per frame: decode JPEG → `preprocess` (lapis 2) → letterbox 320 → YOLOv5n → NMS → temporal filter. Perubahan parameter preprocess dari web berlaku di frame berikutnya tanpa restart (pakai objek konfigurasi yang di-swap secara atomik).
- `power` membaca INA219 setiap 2 s (asyncio task, I/O ringan).
- `status_led` berjalan di thread sendiri agar pola kedip tetap stabil walau event loop sibuk.
- Detector selalu memproses **frame terbaru**, bukan antrean frame (hindari latensi menumpuk).

### 6.4 config.yaml (default awal)
```yaml
glasses:
  stream_url: http://192.168.50.10:81/stream
  offline_timeout_s: 15
mqtt:
  host: 127.0.0.1
  port: 1883
vision:
  model: models/yolov5n_weapon.onnx   # atau folder NCNN (.param + .bin)
  arch: yolov5                        # output [1, N, 5+C], perlu NMS sendiri
  imgsz: 320
  iou: 0.45
  conf: 0.45
  classes: [knife]
  temporal_n: 3        # terdeteksi di 3
  temporal_m: 5        # dari 5 frame terakhir
  max_fps: 5
camera:
  active_preset: default
  preprocess:            # lapis 2, semua bisa diubah dari web
    enabled: true
    rotate: 0            # 0 / 90 / 180 / 270
    flip: none           # none / h / v
    brightness: 0        # −100…100 (offset beta)
    contrast: 1.0        # 0.5…2.0 (alpha)
    saturation: 1.0      # 0.0…2.0 (skala kanal S di HSV)
    gamma: 1.0           # 0.5…2.5
    clahe: false         # perataan histogram lokal untuk kondisi gelap/backlight
    clahe_clip: 2.0
    sharpen: 0.0         # 0…1 (unsharp mask)
    denoise: false       # mahal di CPU, matikan jika FPS turun
    roi: null            # [x, y, w, h] dalam fraksi 0–1, null = seluruh frame
heart_rate:
  high_bpm: 120
  low_bpm: 45
  sustain_s: 10        # harus melewati ambang terus-menerus selama ini
  require_finger: true
gps:
  port: /dev/ttyS5     # VERIFIKASI
  baud: 9600
  stale_s: 30
panic:
  gpio_chip: gpiochip0 # VERIFIKASI
  line: 0              # VERIFIKASI
  debounce_ms: 50
power:
  i2c_bus: 3           # VERIFIKASI (ls /dev/i2c-*, i2cdetect)
  address: 0x40
  shunt_ohm: 0.1
  max_current_a: 3.2
  interval_s: 2
  cells: 2             # VERIFIKASI: jumlah sel baterai seri (lihat K10)
  low_pct: 20
  critical_pct: 8
  shutdown_pct: 5      # simpan data lalu shutdown aman
status_led:
  gpio_chip: gpiochip0 # VERIFIKASI
  lines: {r: 0, g: 0, b: 0}   # VERIFIKASI
  active_low: true     # common anode
alerts:
  cooldown_s:
    weapon: 60
    hr_high: 120
    hr_low: 120
    zone_enter: 300
    panic: 10
    glasses_offline: 300
    battery_low: 600
    battery_critical: 300
speaker:
  device: plughw:1,0   # VERIFIKASI dengan aplay -l
storage:
  db: data/guardian.db
  snapshot_dir: data/snapshots
  retention_days: 7
api:
  host: 0.0.0.0
  port: 8000
```

### 6.5 Skema SQLite
```sql
CREATE TABLE events (
  id TEXT PRIMARY KEY, ts TEXT NOT NULL, type TEXT NOT NULL,
  severity INTEGER NOT NULL, data TEXT, lat REAL, lon REAL,
  loc_src TEXT, snapshot TEXT, notified INTEGER DEFAULT 0,
  acknowledged INTEGER DEFAULT 0
);
CREATE TABLE hr_samples (ts TEXT, bpm INTEGER, finger INTEGER);   -- di-downsample 1 per 5 s
CREATE TABLE gps_track (ts TEXT, lat REAL, lon REAL, sats INTEGER, hdop REAL); -- 1 per 10 s
CREATE TABLE power_samples (ts TEXT, voltage REAL, current_a REAL, power_w REAL, pct INTEGER); -- 1 per 30 s
CREATE TABLE zones (
  id INTEGER PRIMARY KEY, name TEXT, lat REAL, lon REAL,
  radius_m REAL, active INTEGER DEFAULT 1
);
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE camera_presets (
  name TEXT PRIMARY KEY,          -- mis. default, siang, malam, indoor
  sensor TEXT NOT NULL,           -- JSON parameter lapis 1
  preprocess TEXT NOT NULL,       -- JSON parameter lapis 2
  updated TEXT
);
CREATE TABLE outbox (id INTEGER PRIMARY KEY, created TEXT, payload TEXT, tries INTEGER DEFAULT 0);
```
`outbox` menampung notifikasi Telegram yang gagal terkirim saat internet mati.

---

## 7. Logika event (pengganti flowchart linear)

Flowchart lama berjalan berurutan dan berakhir di "Selesai". Implementasinya menjadi **loop paralel**: setiap sumber berjalan terus dan mengirim kejadian ke `event_engine`.

### 7.1 Tabel aturan

| Event | Kondisi | Aksi | Severity |
|---|---|---|---|
| `panic` | Tombol ditekan (setelah debounce) | Alarm web, Telegram + snapshot + lokasi, suara `panic.wav` | 3 |
| `weapon` | Kelas senjata ≥ conf pada N dari M frame | Alarm web, Telegram + snapshot + lokasi, suara `weapon.wav` | 2 |
| `hr_high` | bpm > high_bpm selama sustain_s, finger=true | Alarm web, Telegram + lokasi, suara `hr.wav` | 2 |
| `hr_low` | 0 < bpm < low_bpm selama sustain_s, finger=true | Sama seperti `hr_high` | 2 |
| `zone_enter` | Posisi GPS masuk radius zona aktif (transisi luar → dalam) | Alarm web, Telegram, suara `zone.wav` | 1 |
| `glasses_offline` | LWT `"0"` atau tidak ada status/frame > offline_timeout_s | Alarm web, Telegram, suara `offline.wav` | 2 |
| `gps_lost` | Tidak ada fix > stale_s | Status di web saja (tanpa Telegram) | 1 |
| `battery_low` | % baterai pocket device < low_pct (rata-rata 30 s) | Web, Telegram, suara singkat | 1 |
| `battery_critical` | % baterai < critical_pct | Web, Telegram + lokasi terakhir, suara | 2 |
| (aksi sistem) | % baterai < shutdown_pct | Kirim pesan terakhir, flush SQLite, `shutdown -h now` | — |

### 7.1a Estimasi persen baterai
- Dari tegangan INA219 yang dirata-rata (median 30 s) karena tegangan turun sesaat saat modem mengirim data.
- Tabel tegangan → % untuk Li-ion per sel (contoh: 4.20V=100, 3.85V=60, 3.70V=30, 3.50V=10, 3.30V=0), dikalikan jumlah sel.
- Arus dan daya rata-rata dipakai untuk estimasi sisa waktu: `sisa_Ah / arus_rata2`, jika kapasitas baterai diisi di settings.

### 7.1b Pola LED status (usulan, lihat K9)
Prioritas dari atas ke bawah; kondisi tertinggi yang aktif yang ditampilkan.

| Kondisi | Warna | Pola |
|---|---|---|
| Alarm aktif (panic/weapon/hr) belum di-ack | Merah | Kedip cepat 4 Hz |
| Baterai kritis | Merah | Menyala tetap |
| Baterai rendah | Ungu (R+B) | Kedip lambat 1 Hz |
| Kacamata offline | Biru | Kedip lambat 1 Hz |
| Internet putus atau GPS belum fix | Kuning (R+G) | Menyala tetap |
| Booting / service mulai | Putih (R+G+B) | Kedip 2 Hz |
| Semua normal | Hijau | Kedip singkat tiap 3 s (hemat daya) |

### 7.2 Aturan umum
- **Cooldown per jenis event** agar orang tua tidak dibanjiri notifikasi.
- **Panic tidak pernah diblokir** oleh cooldown jenis lain dan menyela suara lain di speaker.
- Lokasi diambil dari fix GPS terakhir. Jika fix lebih tua dari `stale_s`, tandai `loc_src = last_known` dan sertakan umurnya di pesan.
- Heart rate memicu alarm sendiri sesuai keputusan, tapi wajib: `sustain_s`, `require_finger`, dan cooldown. Nilai ambang dapat diubah dari web.
- Semua event disimpan ke SQLite dan disiarkan lewat WebSocket.

### 7.3 Format pesan Telegram
```
⚠️ [PANIC] Tombol darurat ditekan
Waktu: 22-11-2026 09:30:12
Lokasi: https://maps.google.com/?q=-7.2800,112.7900 (GPS, 3 dtk lalu)
Detak jantung: 128 bpm
```
Kirim `sendPhoto` untuk event dengan snapshot, lalu `sendLocation`.

---

## 8. API dan website

### 8.1 REST
| Method | Path | Fungsi |
|---|---|---|
| POST | `/api/login` | Login (password tunggal, cookie session) |
| GET | `/api/status` | Status terkini: online kacamata, baterai kacamata, baterai pocket device (V, A, W, %), rssi, bpm, GPS, fps deteksi, warna LED |
| GET | `/api/power?minutes=60` | Grafik tegangan, arus, dan % baterai pocket device |
| GET | `/api/events?limit=&type=` | Riwayat event |
| POST | `/api/events/{id}/ack` | Tandai sudah ditangani |
| GET | `/api/hr?minutes=60` | Grafik heart rate |
| GET | `/api/track?minutes=60` | Jejak GPS |
| GET/POST/PUT/DELETE | `/api/zones` | Kelola zona rawan |
| GET/PUT | `/api/settings` | Ambang HR, conf YOLO, cooldown |
| GET | `/api/stream?view=raw\|processed` | MJPEG beranotasi (bounding box), maks 5 fps; `raw` = sebelum preprocess, `processed` = yang dilihat YOLO |
| GET/PUT | `/api/camera/sensor` | Baca/ubah parameter lapis 1 (diteruskan ke `glasses/camera/set`) |
| GET/PUT | `/api/camera/preprocess` | Baca/ubah parameter lapis 2 |
| GET/POST/DELETE | `/api/camera/presets` | Kelola preset; `POST /api/camera/presets/{name}/apply` menerapkan keduanya |
| GET | `/api/camera/snapshot?view=processed` | Satu JPEG untuk membandingkan hasil tuning |
| GET | `/snapshots/{path}` | File snapshot |
| WS | `/ws` | Push `status` (1 Hz) dan `event` (real-time) |

### 8.2 Halaman web (satu halaman, tab)
1. **Live**: video beranotasi, kartu bpm, baterai kacamata, kartu baterai pocket device (%, V, A, estimasi sisa waktu), status koneksi, banner alarm merah + bunyi browser.
2. **Peta**: Leaflet + OpenStreetMap, posisi terkini, jejak 1 jam, lingkaran zona rawan.
3. **Zona**: klik peta → isi nama + radius → simpan.
4. **Riwayat**: daftar event, filter jenis, snapshot, tombol "tandai ditangani".
5. **Kamera**: dua panel slider (Sensor ESP32 dan Pra-pemrosesan SBC), pratinjau berdampingan raw vs processed dengan bounding box, indikator FPS deteksi dan latensi per tahap, tombol simpan sebagai preset, pilih preset, kembali ke default. Slider sensor dikirim dengan debounce ±300 ms agar tidak membanjiri MQTT.
6. **Pengaturan**: ambang HR, sustain, confidence, cooldown, ambang baterai, kapasitas baterai (mAh), uji speaker, uji Telegram, uji LED (siklus warna).

### 8.3 PWA
- `manifest.webmanifest` + `sw.js` cache aset statis saja (data selalu live).
- Install PWA hanya bekerja lewat URL HTTPS Tailscale. Lewat `http://192.168.50.1:8000` tetap berfungsi sebagai web biasa.
- Tile peta butuh internet. Jika offline, peta tampil kosong tapi koordinat tetap ditampilkan sebagai teks.

---

## 9. Model deteksi senjata tajam

1. **Dataset**: gabungkan dataset publik bertema knife/weapon (Roboflow Universe, Open Images kelas "Knife"). Tambahkan gambar negatif (pena, ponsel, sendok, payung, tangan kosong) untuk menekan false positive.
2. **Domain**: setelah kacamata jadi, rekam video dari kamera kacamata sendiri (berbagai jarak, cahaya, gerakan), lalu tambahkan ke dataset. Ini langkah yang paling berpengaruh pada akurasi.
3. **Training** (YOLOv5n, di Colab/PC dengan GPU):
   ```bash
   git clone https://github.com/ultralytics/yolov5 && cd yolov5
   pip install -r requirements.txt
   python train.py --img 320 --batch 64 --epochs 150 \
     --data ../model/data.yaml --weights yolov5n.pt --name weapon_v5n
   ```
   Augmentasi tambahan yang relevan: variasi kecerahan/saturasi (HSV), blur gerak, JPEG berkualitas rendah — mendekati kondisi kamera kacamata.
4. **Ekspor**:
   ```bash
   python export.py --weights runs/train/weapon_v5n/weights/best.pt \
     --include onnx --img 320 --opset 12 --simplify
   ```
   Opsional NCNN: konversi ONNX dengan `pnnx`/`onnx2ncnn`. Salin hasil ke `sbc/models/`.
   Output YOLOv5 berbentuk `[1, N, 5 + jumlah_kelas]` (xywh, objectness, skor kelas); `detector.py` mengalikan objectness × skor kelas lalu NMS.
5. **Benchmark** dengan `tools/bench_detector.py` di Orange Pi: catat FPS, latensi, penggunaan RAM dan suhu CPU.
6. **Evaluasi**: precision/recall di data uji kacamata, bukan hanya di validation set publik.
7. **Konsistensi tuning**: rekam data kacamata untuk dataset **dengan preset kamera yang sama** dengan yang dipakai saat operasi. Jika preset sensor/preprocess diubah drastis setelah training, akurasi bisa turun; uji ulang setiap kali preset utama berubah.

> Lisensi: YOLOv5 berlisensi AGPL-3.0. Aman untuk riset/lomba; perlu ditinjau ulang bila produk dikomersialkan.

### 9.1 Pembagian data
- Bagi train/val/test **per sesi rekaman**, bukan per frame (cegah kebocoran frame mirip).
- Test set **hanya data primer**. Patokan 70/20/10.
- Training dua tahap: (1) data sekunder → (2) fine-tune gabungan sekunder + primer (primer di-oversample bila jauh lebih sedikit).
- Ambang confidence dipilih dari kurva PR di test primer, mengutamakan recall; false positive diredam filter temporal.

---

## 9A. Rencana pengambilan data primer

### 9A.1 Tujuan
Mengisi celah yang tidak ada di data sekunder: sudut pandang orang pertama dari kacamata, resolusi dan kompresi kamera ESP32, gerakan kepala, kondisi cahaya lokal, dan jenis senjata tajam lokal.

### 9A.2 Strategi kelas (lihat K13)
Saat **melabeli**, gunakan kelas rinci: `pisau`, `celurit`, `parang_golok`, `gunting`, `lainnya_tajam`. Kelas rinci bisa digabung belakangan menjadi satu kelas `senjata_tajam` hanya dengan mengubah `data.yaml` dan memetakan ulang indeks. Arah sebaliknya, dari satu kelas ke kelas rinci, memaksa labeling ulang. Keputusan kelas untuk **training** tetap di K13.

### 9A.3 Alat
- Kacamata final (posisi kamera sama dengan saat operasi) dan preset kamera yang dipakai saat operasi (catat nama preset di setiap sesi).
- Pocket device dengan mode rekam dataset (lihat 9A.7).
- Benda uji: pisau dapur, pisau lipat, celurit, parang/golok, gunting. **Mata pisau ditumpulkan atau dilapisi selotip bening** bila memungkinkan.
- Benda negatif sulit: pena, ponsel, sendok, garpu, sisir, remote, obeng, payung lipat, botol, tongkat kayu.
- Lembar persetujuan relawan.

### 9A.4 Matriks skenario
Setiap sesi memilih satu kombinasi; targetkan semua sel terisi minimal sekali.

| Faktor | Variasi |
|---|---|
| Jarak benda ke kamera | Dekat 0.5–1 m, sedang 1–3 m, jauh 3–5 m |
| Cahaya | Siang luar ruang, teduh/mendung, indoor lampu, malam lampu jalan, backlight (melawan matahari/jendela) |
| Gerak pemakai | Diam, berjalan pelan, menoleh |
| Cara benda tampak | Dipegang di samping badan, diangkat, tergeletak, sebagian tertutup tangan/baju, dikeluarkan dari tas/pinggang |
| Latar | Jalan/gang, parkiran, ruang kelas/kantor, dapur, warung/pasar |
| Orang dalam frame | 0, 1, 2+ |

### 9A.5 Target jumlah (awal, direvisi setelah evaluasi pertama)
| Data | Target fase 1 | Target fase 2 |
|---|---|---|
| Gambar berlabel positif per kelas rinci | ≥ 300 | ≥ 1.000 |
| Gambar negatif (tanpa senjata) | ≥ 300 | ≥ 1.000 |
| Sesi rekaman terpisah | ≥ 15 | ≥ 40 |
| Test set primer (sesi yang tidak dipakai training) | ≥ 3 sesi | ≥ 8 sesi |

### 9A.6 Protokol per sesi
1. Pilih sel matriks, isi baris di `dataset_log.csv` sebelum mulai.
2. Cek preset kamera dan baterai kedua perangkat.
3. Rekam 1–3 menit per skenario. Relawan menampilkan benda secara wajar; **tidak pernah diarahkan ke orang**.
4. Rekam 30–60 detik skenario negatif di lokasi yang sama (benda negatif sulit).
5. Cek cuplikan rekaman di lokasi sebelum pindah skenario.
6. Akhiri sesi: salin data, isi catatan kendala.

### 9A.7 Mode rekam dataset di pocket device
- Tambah `tools/record_session.py` dan tombol **Rekam dataset** di halaman Kamera.
- Menyimpan frame **mentah dari ESP32 (sebelum preprocess lapis 2)** sebagai JPEG berurutan, ditambah `meta.json` (preset sensor, preset preprocess, waktu, GPS, catatan).
- Detector boleh dimatikan saat merekam agar FPS rekaman maksimal.
- Struktur penyimpanan:
```
dataset_raw/
└── S017_2026-12-03_malam_jalan/
    ├── meta.json
    └── frames/000001.jpg ...
```
- `dataset_log.csv`: `session_id, tanggal, lokasi, cahaya, jarak, gerak, benda, relawan_id, preset, durasi_s, jumlah_frame, catatan`.

### 9A.8 Seleksi frame
- Ambil 1 dari tiap 10 frame (atur sesuai FPS), lalu buang frame yang terlalu mirip (hash perseptual) dan frame rusak/sepenuhnya blur.
- Frame dari momen paling sulit (jauh, gelap, sebagian tertutup) diprioritaskan.

### 9A.9 Pedoman labeling
- Alat: Roboflow, CVAT, atau Label Studio, ekspor format YOLO.
- Kotak rapat mengikuti bagian benda yang terlihat, termasuk gagang.
- Benda tertutup sebagian tetap dilabeli bila ≥ 30% terlihat dan masih bisa dikenali manusia.
- Benda lebih kecil dari ±8 px pada resolusi asli diabaikan secara konsisten.
- Gambar negatif tetap dimasukkan dengan file label kosong.
- QA: orang kedua memeriksa acak 10% gambar per sesi; ketidaksepakatan dibahas lalu pedoman diperbarui.

### 9A.10 Etika, keselamatan, dan privasi
- Pengambilan data dilakukan di tempat terkendali atau tempat umum dengan izin; hindari menimbulkan kepanikan orang sekitar (rekam di area tertutup untuk skenario benda diangkat/dikeluarkan).
- Relawan dewasa, menandatangani persetujuan, boleh berhenti kapan saja.
- Data mentah tidak dipublikasikan; wajah relawan diburamkan jika gambar dipakai di paper/presentasi.
- Simpan dataset di penyimpanan pribadi, bukan repo publik.

### 9A.11 Jadwal (usulan, sesuaikan)
| Minggu | Kegiatan |
|---|---|
| 1 | Siapkan mode rekam, lembar persetujuan, benda uji, uji coba 2 sesi |
| 2–3 | Sesi fase 1 (≥ 15 sesi), labeling bertahap |
| 4 | Training tahap 2, evaluasi, analisis kesalahan |
| 5–6 | Sesi fase 2 menyasar kondisi yang paling sering gagal |

Struktur:
```
model/
├── train.ipynb
├── data.yaml
└── README.md   # sumber dataset + lisensinya
```

---

## 10. Workflow pengembangan

### 10.1 Repo (monorepo)
```
guardian/
├── plan.md
├── CLAUDE.md          # ringkasan aturan untuk Claude Code (dibuat di M0)
├── firmware/          # PlatformIO, dikerjakan di laptop
├── sbc/               # Python, dikerjakan via Remote-SSH di Orange Pi
├── model/             # training
└── docs/              # wiring, foto, hasil uji
```

### 10.2 Cara kerja
- **Firmware**: buka `firmware/` di VS Code lokal, build/upload lewat PlatformIO, serial monitor 115200.
- **SBC**: VS Code Remote-SSH ke `orangepi@<ip>` (lewat Wi-Fi AP atau Tailscale), buka `/home/orangepi/guardian/sbc`, jalankan Claude Code di terminal remote.
- **Sinkronisasi**: git (push dari laptop, pull di Orange Pi) atau clone langsung di Orange Pi.
- **Tanpa hardware**: gunakan `tools/fake_glasses.py` dan `tools/fake_gps.py` agar backend dan web bisa diuji di laptop.
- Jalankan sebagai service setelah stabil:
```ini
# systemd/guardian.service
[Unit]
Description=Guardian pocket device
After=network-online.target mosquitto.service
Wants=network-online.target

[Service]
User=orangepi
WorkingDirectory=/home/orangepi/guardian/sbc
EnvironmentFile=/home/orangepi/guardian/sbc/.env
ExecStart=/home/orangepi/guardian/sbc/.venv/bin/python -m guardian
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

---

## 11. Milestone

| # | Milestone | Kriteria lulus |
|---|---|---|
| M0 | Setup repo + Orange Pi OS, SSH, Tailscale, venv, Mosquitto | SSH via Tailscale jalan; `mosquitto_sub` menerima pesan uji |
| M1 | Firmware: kamera MJPEG | `/stream` tampil di browser laptop, ≥10 fps QVGA |
| M2 | Firmware: MAX30102 + MQTT + LWT + tuning kamera | `glasses/hr` muncul 1 Hz; mencabut daya ESP memicu `glasses/online = 0`; `mosquitto_pub` ke `glasses/camera/set` mengubah gambar stream secara langsung dan nilainya bertahan setelah reboot ESP |
| M3 | Jaringan: Orange Pi sebagai AP + modem USB | Kacamata dan HP terhubung ke AP; Orange Pi tetap online via modem; Tailscale tetap jalan |
| M4 | SBC: ingest (stream, MQTT, GPS, panic button, INA219) + LED status + simulator | Log menunjukkan frame/detik, bpm, koordinat, tekanan tombol, serta V/A/W baterai yang cocok dengan multimeter (selisih < 2%); `i2cdetect` menemukan 0x40; perintah uji LED menyalakan R, G, B, kuning, ungu, putih dengan benar |
| M5 | SBC: preprocess + detector YOLOv5n + benchmark (awal: `yolov5n.pt` COCO untuk uji pipeline) | `bench_detector.py` mencatat FPS dan latensi per tahap (decode, preprocess, inferensi, NMS) di Orange Pi untuk ONNX Runtime dan NCNN; bounding box tampil di `/api/stream`; mengubah parameter preprocess tidak memerlukan restart |
| M6 | SBC: event engine + SQLite + Telegram + speaker + LED | Setiap event di tabel 7.1 bisa dipicu (simulator/tombol, baterai via nilai palsu) → tersimpan, notifikasi Telegram terkirim, suara keluar, LED berganti sesuai 7.1b; outbox terkirim ulang setelah internet kembali; shutdown aman teruji dengan nilai palsu |
| M7 | Website + PWA | Semua halaman 8.2 berfungsi; alarm muncul < 2 dtk setelah event; PWA ter-install via URL Tailscale |
| M7b | Mode rekam dataset (9A.7) | Tombol rekam di web menghasilkan folder sesi berisi frame mentah + `meta.json`; FPS rekaman tercatat |
| M8 | Model senjata tajam terlatih (data sekunder + primer, 9 dan 9A) | Model menggantikan COCO; precision/recall/mAP50 di test set primer dicatat di `docs/`, beserta daftar kondisi yang masih gagal |
| M9 | Integrasi + uji lapangan + systemd | Sistem menyala otomatis setelah boot; uji 1 jam tanpa crash; ukur konsumsi daya dan durasi baterai kedua perangkat |

---

## 12. Keputusan terbuka (tanyakan ke user sebelum memutuskan)

| ID | Pertanyaan | Opsi |
|---|---|---|
| K1 | ~~Versi YOLO~~ | **Diputuskan: YOLOv5n 320** |
| K2 | Runtime inferensi | ONNX Runtime (mudah) vs NCNN (lebih cepat di ARM) — putuskan setelah benchmark M5 |
| K3 | Pin UART GPS dan GPIO panic button | Tentukan setelah cek manual resmi Zero 2W |
| K4 | Resolusi stream | QVGA (lebih cepat) vs VGA (objek kecil lebih terlihat) — putuskan setelah M5 |
| K5 | Ambang HR default | 120/45 bpm dan sustain 10 s adalah tebakan awal; tetapkan setelah uji M2 di pemakai |
| K6 | Rekaman klip video saat event | v1 hanya snapshot; klip pre/post event bisa di v2 |
| K7 | Isi suara arahan | Teks rekaman tiap WAV dan apakah suara keras justru berisiko memancing penyerang |
| K8 | Retensi data dan privasi | Lama simpan snapshot/jejak GPS, siapa yang boleh mengakses |
| K9 | Rangkaian dan pola LED RGB | Anoda 3.3V + resistor kecil (sederhana, hijau/biru mungkin redup) vs anoda 5V + 3 transistor (terang, butuh komponen tambahan); setujui atau ubah tabel 7.1b |
| K10 | Spesifikasi baterai pocket device | Jumlah sel (1S/2S/3S), kapasitas mAh, jenis (Li-ion/LiPo/LiFePO4) — menentukan tabel tegangan → % dan pilihan regulator |
| K12 | Preset kamera bawaan | Preset apa saja yang disiapkan (mis. siang, malam, indoor) dan apakah preset berganti otomatis berdasarkan kecerahan frame atau hanya manual |
| K13 | Kelas untuk training | (a) `knife` saja, (b) satu kelas `senjata_tajam` gabungan, (c) kelas terpisah per jenis. Labeling tetap rinci (9A.2) |
| K14 | Target jumlah data dan jadwal 9A.5/9A.11 | Disesuaikan dengan ketersediaan relawan, benda uji, dan tenggat lomba |
| K11 | Posisi INA219 | Sisi baterai sebelum regulator (mengukur total konsumsi, disarankan) vs sisi 5V setelah regulator (tidak melihat rugi regulator) |

---

## 13. Risiko yang perlu dipantau

- **FPS inferensi** di H618 tanpa NPU mungkin hanya beberapa FPS. Pipeline harus tetap benar walau FPS rendah.
- **Satu radio Wi-Fi** Orange Pi dipakai sebagai AP; internet sepenuhnya bergantung pada modem USB.
- **Daya**: modem 4G + YOLO + Wi-Fi AP + amplifier menarik arus puncak besar. Ukur sebelum memilih baterai.
- **Suhu**: inferensi terus-menerus memanaskan H618 di dalam casing tertutup. Pantau `/sys/class/thermal`.
- **Heart rate sebagai alarm mandiri** rawan alarm palsu saat berlari atau naik tangga. Ambang dan sustain harus divalidasi.
- **Domain gap model**: dataset publik berbeda dengan sudut pandang kacamata.
- **Satu port USB**: hub wajib; pilih hub yang stabil dan tidak memutus perangkat saat arus modem melonjak.
- **Pra-pemrosesan di SBC memakan CPU** yang sama dengan YOLO. CLAHE dan denoise paling mahal; utamakan tuning di sensor (lapis 1), gunakan lapis 2 seperlunya.
- **Estimasi % baterai dari tegangan** tidak presisi saat beban berubah-ubah; perlakukan sebagai perkiraan, kalibrasi dengan uji discharge penuh.
- **Batas arus INA219** (±3.2 A dengan shunt 0.1 Ω) bisa terlampaui saat puncak; pembacaan akan saturasi.
