#pragma once
#include <Arduino.h>

// Koneksi WiFi + MQTT, publish data, LWT, dan perintah dari SBC (plan.md 4.2).
// Semua akses PubSubClient terjadi di netTask (core 0) karena library tidak thread-safe.
//
// Publish : glasses/hr (1 s), glasses/status (10 s), glasses/online ("1"/LWT "0", retained),
//           glasses/camera/state (retained, saat connect & setelah tiap set)
// Subscribe: glasses/cmd, glasses/camera/set
namespace mqtt_link {

void start();  // buat netTask (WiFi harus sudah WiFi.begin())

}  // namespace mqtt_link
