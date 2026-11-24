# Firmware kacamata Guardian (XIAO ESP32S3 Sense)

Firmware ringan sesuai `../plan.md` bagian 5. ESP **hanya**:
- menyajikan kamera sebagai MJPEG di `http://192.168.50.10:81/stream` (dan satu JPEG di `/capture`),
- mengirim heart rate, status, dan LWT lewat MQTT ke Mosquitto di Orange Pi,
- menerima tuning parameter sensor kamera dari SBC.

Deteksi senjata, alarm, Telegram, dan zona ada di pocket device (`../sbc`).

## Struktur
| File | Isi |
|---|---|
| `src/main.cpp` | urutan boot, WiFi STA (IP statis) |
| `src/camera_server.*` | init kamera (buffer SVGA di PSRAM, `GRAB_LATEST`), HTTP :81 di core 1 |
| `src/camera_tuning.*` | parameter sensor (plan 5.6), validasi rentang, simpan NVS |
| `src/heart_rate.*` | MAX30102, median 7 detak, rentang 30–220 bpm, task ~100 Hz di core 0 |
| `src/mqtt_link.*` | netTask core 0: WiFi + MQTT reconnect (backoff 1–30 s), publish, LWT, perintah |
| `src/battery.*` | pembagi tegangan 2×100k di GPIO4 |
| `include/config.h` | pin, interval, ambang (masuk git) |
| `include/secrets.h` | SSID/password AP, IP broker, IP statis (tidak masuk git; template `secrets.example.h`) |

## Wiring
| Komponen | Pin |
|---|---|
| Kamera | konektor B2B board Sense (`include/camera_pins.h`) |
| MAX30102 | SDA = D4 (GPIO5), SCL = D5 (GPIO6), 3V3, GND |
| Baterai | BAT+ → 100k → **GPIO4 (D3)** → 100k → GND (`BATTERY_ENABLED 0` jika belum dipasang) |

## Build & upload
1. Isi `include/secrets.h` (password AP `guardian-ap` milik Orange Pi).
2. `pio run -t upload`, lalu `pio device monitor` (115200). Setelah WiFi tersambung, alamat stream dicetak di serial.

## Kontrak MQTT (plan 4.2)
| Topik | Arah | Isi |
|---|---|---|
| `glasses/hr` | ESP → SBC, 1 s | `{"bpm":82,"finger":true,"ir":51234,"ts":123456}`; sensor lepas → `finger:false, bpm:0` |
| `glasses/status` | ESP → SBC, 10 s | `{"batt_mv","rssi","uptime","heap","cam_ok","fps","stream","hr_ok","fw"}` |
| `glasses/online` | ESP → SBC | `"1"` saat connect; LWT `"0"` (retained, QoS1). Keepalive 10 s |
| `glasses/camera/set` | SBC → ESP | sebagian parameter, mis. `{"brightness":1,"vflip":1,"framesize":"VGA"}` |
| `glasses/camera/state` | ESP → SBC | semua parameter aktif + `"sensor"` + `"errors"` dari set terakhir (retained) |
| `glasses/cmd` | SBC → ESP | `{"stream":false}` matikan stream (/stream → 503), `{"stream":true}`, `{"reboot":true}` |

Parameter sensor: `framesize` (QQVGA/QVGA/CIF/VGA/SVGA), `quality` 4–63, `brightness/contrast/saturation/sharpness`
−2..2, `awb` 0/1, `wb_mode` 0–4, `aec` 0/1, `aec_value` 0–1200, `ae_level` −2..2, `agc` 0/1, `agc_gain` 0–30,
`gainceiling` 0–6, `hmirror/vflip/lenc/bpc/wpc/raw_gma/dcw` 0/1. Boolean boleh `true/false` atau `0/1`.
Nilai di luar rentang ditolak dan dicatat di `errors`. Ganti `framesize` memutus stream sebentar, dan SBC
menyambung ulang otomatis.

Catatan: PubSubClient hanya bisa publish QoS0. `online`/`camera/state` tetap retained, LWT memakai QoS1.

## Uji (milestone M1/M2)
```bash
# M1: buka di browser laptop yang terhubung ke guardian-ap (target >= 10 fps QVGA)
http://192.168.50.10:81/stream
# M2 (di Orange Pi)
mosquitto_sub -v -t 'glasses/#'
mosquitto_pub -t glasses/camera/set -m '{"brightness":2,"vflip":1}'   # gambar berubah, bertahan setelah reboot
mosquitto_pub -t glasses/camera/set -m '{"quality":99}'               # ditolak -> errors di camera/state
# cabut daya ESP -> glasses/online 0 dalam ~15 s
```

## Kalibrasi heart rate
Perhatikan `ir` di `glasses/hr`. Tanpa kulit, nilainya harus di bawah `HR_AMBANG_IR` (50000). Saat menempel,
nilainya jauh di atas ambang itu tapi < 250000 (jenuh). Sinyal lemah → naikkan `HR_LED_ARUS`. Sinyal jenuh → turunkan.
