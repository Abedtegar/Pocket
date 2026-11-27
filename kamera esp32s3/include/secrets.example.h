#pragma once
/*
 * Salin menjadi secrets.h lalu isi. secrets.h tidak ikut git.
 */

// Wi-Fi yang sama dengan Orange Pi (mis. Wi-Fi modem USB 4G)
#define WIFI_SSID "nama-wifi"
#define WIFI_PASS "password-wifi"

// Broker MQTT = Orange Pi. Nama mDNS (hostname Orange Pi + ".local"), nama DNS, atau IP.
#define MQTT_HOST "guardian.local"
#define MQTT_PORT 1883

// Kosong = DHCP (disarankan; kacamata dicari lewat guardian-glasses.local).
// Isi hanya bila perlu IP tetap, dan harus satu subnet dengan Wi-Fi di atas.
#define STATIC_IP ""
#define STATIC_GATEWAY ""
#define STATIC_SUBNET "255.255.255.0"
