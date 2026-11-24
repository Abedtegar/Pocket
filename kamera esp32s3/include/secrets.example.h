#pragma once
/*
 * Salin menjadi secrets.h lalu isi. secrets.h tidak ikut git.
 * Nilai default mengikuti plan.md bagian 3 (AP milik Orange Pi).
 */

#define WIFI_SSID "guardian-ap"
#define WIFI_PASS "ganti-dengan-password-ap"

#define MQTT_HOST "192.168.50.1"
#define MQTT_PORT 1883

// IP statis kacamata. Kosongkan STATIC_IP untuk memakai DHCP
// (maka SBC harus diberi tahu IP-nya lewat glasses.stream_url).
#define STATIC_IP "192.168.50.10"
#define STATIC_GATEWAY "192.168.50.1"
#define STATIC_SUBNET "255.255.255.0"
