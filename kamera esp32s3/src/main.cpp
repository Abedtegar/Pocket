/*
 * Guardian - firmware kacamata (Seeed XIAO ESP32S3 Sense), plan.md bagian 5
 * ========================================================================
 * Ringan: ESP hanya streaming kamera dan mengirim data sensor. Semua logika
 * (deteksi YOLO, alarm, notifikasi, zona) ada di pocket device (Orange Pi).
 *
 *   camera_server.cpp - init kamera + HTTP MJPEG :81/stream, /capture   (core 1)
 *   camera_tuning.cpp - parameter sensor dari glasses/camera/set, simpan NVS
 *   heart_rate.cpp    - MAX30102 -> bpm, task ~100 Hz                    (core 0)
 *   mqtt_link.cpp     - WiFi + MQTT: hr 1 s, status 10 s, LWT, cmd      (core 0)
 *   battery.cpp       - tegangan baterai dari pembagi tegangan
 *   config.h / secrets.h - konstanta / kredensial (secrets.h tidak ikut git)
 */

#include <Arduino.h>
#include <WiFi.h>

#include "battery.h"
#include "camera_pins.h"
#include "camera_server.h"
#include "camera_tuning.h"
#include "config.h"
#include "heart_rate.h"
#include "mqtt_link.h"
#include "secrets.h"

static void kedip(int n) {
  for (int i = 0; i < n; i++) {
    digitalWrite(LED_GPIO_NUM, LOW);  // LED onboard aktif LOW
    delay(120);
    digitalWrite(LED_GPIO_NUM, HIGH);
    delay(120);
  }
}

static void mulaiWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);  // tanpa ini stream tersendat karena modem power-save
  WiFi.setAutoReconnect(true);

  if (strlen(STATIC_IP) > 0) {
    IPAddress ip, gw, sn;
    if (ip.fromString(STATIC_IP) && gw.fromString(STATIC_GATEWAY) && sn.fromString(STATIC_SUBNET)) {
      WiFi.config(ip, gw, sn, gw);  // DNS = gateway (Orange Pi)
      Serial.printf("[wifi] IP statis %s\n", STATIC_IP);
    } else {
      Serial.println("[wifi] STATIC_IP/GATEWAY/SUBNET salah format - memakai DHCP");
    }
  }
  WiFi.begin(WIFI_SSID, WIFI_PASS);  // non-blocking; netTask menjaga koneksi
  Serial.printf("[wifi] menghubungkan ke %s...\n", WIFI_SSID);
}

void setup() {
  Serial.begin(115200);
  delay(300);  // beri waktu USB CDC siap
  pinMode(LED_GPIO_NUM, OUTPUT);
  digitalWrite(LED_GPIO_NUM, HIGH);
  Serial.println("\n=== Guardian glasses " FW_VERSION " ===");

  if (!camera_server::initCamera()) {
    Serial.println("Kamera gagal. Periksa konektor B2B papan kamera. Restart 5 detik lagi...");
    delay(5000);
    ESP.restart();
  }
  camera_tuning::begin();

  heart_rate::begin();  // tidak fatal: kamera tetap jalan tanpa sensor HR
  battery::begin();

  mulaiWifi();
  camera_server::startHttp();
  mqtt_link::start();

  kedip(2);
  Serial.println("Siap. Alamat stream dicetak setelah WiFi terhubung.");
}

void loop() {
  // Semua kerja ada di task FreeRTOS (httpd, hr, net). loop() tidak dipakai.
  vTaskDelete(nullptr);
}
