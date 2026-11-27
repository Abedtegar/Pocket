#pragma once
/*
 * Konstanta firmware kacamata (tanpa rahasia - boleh masuk git).
 * Kredensial WiFi dan alamat broker ada di secrets.h (tidak ikut git).
 */

#define FW_VERSION "2.0.0"

// ------------------------------------------------------------------ mDNS
// Kacamata dapat diakses sebagai http://guardian-glasses.local:81/stream
// (juga dipakai sebagai hostname DHCP, sebagian modem ikut mendaftarkannya di DNS-nya).
#define MDNS_NAME "guardian-glasses"

// ------------------------------------------------------------- kamera / HTTP
#define STREAM_PORT 81          // GET /stream (MJPEG), GET /capture (JPEG)
// Frame buffer dialokasikan untuk resolusi terbesar yang boleh dipilih dari web
// (SVGA). Resolusi aktif lalu diturunkan sesuai preset (default QVGA). Init di
// resolusi kecil lalu menaikkannya belakangan membuat buffer JPEG kekecilan.
#define CAMERA_MAX_FRAMESIZE FRAMESIZE_SVGA
#define CAMERA_XCLK_HZ 20000000

// ------------------------------------------------------------------ MQTT
#define MQTT_KEEPALIVE_S 10     // LWT terkirim ~1,5x keepalive setelah daya hilang
#define HR_PUBLISH_MS 1000      // glasses/hr
#define STATUS_PUBLISH_MS 10000 // glasses/status

// ------------------------------------------------------------- heart rate
#define HR_SDA_PIN 5            // D4
#define HR_SCL_PIN 6            // D5
#define HR_AMBANG_IR 50000L     // di bawah ini = sensor tidak menempel (finger:false)
#define HR_LED_ARUS 0x1F        // arus LED IR; naikkan kalau sinyal lemah
#define HR_SAMPLE_AVG 4         // 400 Hz / 4 = 100 sampel per detik
#define HR_JENDELA 7            // median dari 7 detak terakhir (ganjil, 3-15)
#define HR_BPM_VALID_MIN 30     // interval di luar 30-220 bpm dibuang
#define HR_BPM_VALID_MAX 220
#define HR_TOLAK_GANDA 1        // buang interval ~2x median (denyut terlewat)

// ---------------------------------------------------------------- baterai
// Pembagi tegangan 2x100k dari BAT+ ke GPIO4 (D3). 0 = belum terpasang -> batt_mv 0.
#define BATTERY_ENABLED 1
#define BATTERY_PIN 4
#define BATTERY_R1 100000.0f    // BAT+ -> pin
#define BATTERY_R2 100000.0f    // pin -> GND
