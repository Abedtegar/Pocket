#include "mqtt_link.h"

#include <ArduinoJson.h>
#include <ESPmDNS.h>
#include <PubSubClient.h>
#include <WiFi.h>

#include "battery.h"
#include "camera_server.h"
#include "camera_tuning.h"
#include "config.h"
#include "heart_rate.h"
#include "secrets.h"

static const char *T_HR = "glasses/hr";
static const char *T_STATUS = "glasses/status";
static const char *T_ONLINE = "glasses/online";
static const char *T_CMD = "glasses/cmd";
static const char *T_CAM_SET = "glasses/camera/set";
static const char *T_CAM_STATE = "glasses/camera/state";

static WiFiClient g_net;
static PubSubClient g_mqtt(g_net);
static char g_client_id[32];

// Ditandai di callback, dikerjakan di loop netTask (callback tidak boleh publish
// karena payload menunjuk ke buffer yang sama dengan buffer publish).
static bool g_state_dirty = false;
static bool g_reboot = false;

static void onMessage(char *topic, byte *payload, unsigned int len) {
  // Salin payload: buffer PubSubClient dipakai ulang saat publish berikutnya.
  String body;
  body.reserve(len);
  for (unsigned int i = 0; i < len; i++) body += (char)payload[i];

  if (!strcmp(topic, T_CAM_SET)) {
    bool fsChanged = false;
    camera_tuning::applyJson(body.c_str(), body.length(), fsChanged);
    if (fsChanged) camera_server::restartStream();  // SBC menyambung ulang otomatis
    g_state_dirty = true;
  } else if (!strcmp(topic, T_CMD)) {
    JsonDocument doc;
    if (deserializeJson(doc, body)) return;
    if (doc["stream"].is<bool>()) camera_server::setStreamEnabled(doc["stream"].as<bool>());
    if (doc["reboot"] | false) g_reboot = true;
  }
}

// MQTT_HOST boleh berupa IP ("192.168.8.100"), nama mDNS ("guardian.local"), atau nama DNS biasa.
static bool resolveBroker(IPAddress &ip) {
  const char *h = MQTT_HOST;
  if (ip.fromString(h)) return true;
  size_t n = strlen(h);
  if (n > 6 && !strcasecmp(h + n - 6, ".local")) {
    String name(h);
    name.remove(n - 6);  // queryHost() menerima nama tanpa ".local"
    IPAddress r = MDNS.queryHost(name.c_str(), 2000);
    if (r == IPAddress()) {
      Serial.printf("[mqtt] %s tidak ditemukan lewat mDNS (Orange Pi mati / avahi belum jalan?)\n", h);
      return false;
    }
    ip = r;
    return true;
  }
  if (WiFi.hostByName(h, ip) != 1) {
    Serial.printf("[mqtt] DNS gagal untuk %s\n", h);
    return false;
  }
  return true;
}

static bool connectMqtt() {
  IPAddress broker;
  if (!resolveBroker(broker)) return false;
  g_mqtt.setServer(broker, MQTT_PORT);

  // LWT "0" retained QoS1: broker mengirimnya bila kacamata hilang tanpa disconnect.
  if (!g_mqtt.connect(g_client_id, nullptr, nullptr, T_ONLINE, 1, true, "0", true)) {
    Serial.printf("[mqtt] gagal connect ke %s (%s):%d (rc=%d)\n", MQTT_HOST, broker.toString().c_str(),
                  MQTT_PORT, g_mqtt.state());
    return false;
  }
  Serial.printf("[mqtt] terhubung ke %s (%s):%d sebagai %s\n", MQTT_HOST, broker.toString().c_str(), MQTT_PORT,
                g_client_id);
  g_mqtt.subscribe(T_CMD, 1);
  g_mqtt.subscribe(T_CAM_SET, 1);
  g_mqtt.publish(T_ONLINE, "1", true);
  g_state_dirty = true;  // kirim seluruh parameter aktif saat connect
  return true;
}

static void publishHr() {
  JsonDocument doc;
  doc["bpm"] = heart_rate::bpm();
  doc["finger"] = heart_rate::finger();
  doc["ir"] = heart_rate::ir();
  doc["ts"] = millis();
  char buf[128];
  size_t n = serializeJson(doc, buf, sizeof(buf));
  g_mqtt.publish(T_HR, (const uint8_t *)buf, n, false);
}

static void publishStatus() {
  JsonDocument doc;
  doc["batt_mv"] = battery::millivolts();
  doc["rssi"] = WiFi.RSSI();
  doc["uptime"] = millis() / 1000;
  doc["heap"] = ESP.getFreeHeap();
  doc["cam_ok"] = camera_server::cameraOk();
  doc["fps"] = roundf(camera_server::streamFps() * 10) / 10;
  doc["stream"] = camera_server::streamEnabled();
  doc["hr_ok"] = heart_rate::available();
  doc["fw"] = FW_VERSION;
  char buf[256];
  size_t n = serializeJson(doc, buf, sizeof(buf));
  g_mqtt.publish(T_STATUS, (const uint8_t *)buf, n, false);
}

static void netTask(void *) {
  uint32_t wifi_lost_since = 0;
  uint32_t next_mqtt_try = 0;
  uint32_t backoff = 1000;
  uint32_t last_hr = 0, last_status = 0;
  bool was_connected = false;

  for (;;) {
    uint32_t now = millis();

    // ---- WiFi
    if (WiFi.status() != WL_CONNECTED) {
      if (was_connected) {
        Serial.println("[wifi] terputus");
        was_connected = false;
      }
      if (!wifi_lost_since) wifi_lost_since = now;
      if (now - wifi_lost_since > 15000) {  // auto-reconnect bawaan tidak berhasil
        Serial.println("[wifi] menyambung ulang...");
        WiFi.disconnect();
        WiFi.begin(WIFI_SSID, WIFI_PASS);
        wifi_lost_since = now;
      }
      vTaskDelay(pdMS_TO_TICKS(200));
      continue;
    }
    if (!was_connected) {
      Serial.printf("[wifi] terhubung %s, IP %s, RSSI %d\n", WIFI_SSID, WiFi.localIP().toString().c_str(),
                    WiFi.RSSI());
      Serial.printf("[wifi] stream: http://%s:%d/stream\n", WiFi.localIP().toString().c_str(), STREAM_PORT);
      static bool mdns_started = false;
      if (!mdns_started && MDNS.begin(MDNS_NAME)) {
        MDNS.addService("http", "tcp", STREAM_PORT);
        mdns_started = true;
        Serial.printf("[wifi] mDNS: http://%s.local:%d/stream\n", MDNS_NAME, STREAM_PORT);
      }
      was_connected = true;
      next_mqtt_try = 0;
    }
    wifi_lost_since = 0;

    // ---- MQTT (backoff 1 s -> 30 s; kamera tetap jalan saat MQTT putus)
    if (!g_mqtt.connected()) {
      if ((int32_t)(now - next_mqtt_try) >= 0) {
        if (connectMqtt()) {
          backoff = 1000;
        } else {
          next_mqtt_try = now + backoff;
          backoff = backoff * 2 > 30000 ? 30000 : backoff * 2;
        }
      }
    } else {
      g_mqtt.loop();
      if (g_state_dirty) {
        g_state_dirty = false;
        String st = camera_tuning::stateJson();
        g_mqtt.publish(T_CAM_STATE, (const uint8_t *)st.c_str(), st.length(), true);
      }
      if (now - last_hr >= HR_PUBLISH_MS) {
        last_hr = now;
        publishHr();
      }
      if (now - last_status >= STATUS_PUBLISH_MS) {
        last_status = now;
        publishStatus();
      }
      if (g_reboot) {
        Serial.println("[mqtt] perintah reboot");
        g_mqtt.publish(T_ONLINE, "0", true);
        g_mqtt.disconnect();
        vTaskDelay(pdMS_TO_TICKS(200));
        ESP.restart();
      }
    }
    vTaskDelay(pdMS_TO_TICKS(20));
  }
}

void mqtt_link::start() {
  uint8_t mac[6];
  WiFi.macAddress(mac);
  snprintf(g_client_id, sizeof(g_client_id), "glasses-%02x%02x%02x", mac[3], mac[4], mac[5]);
  g_mqtt.setCallback(onMessage);
  g_mqtt.setBufferSize(1024);  // camera/state ~400 byte
  g_mqtt.setKeepAlive(MQTT_KEEPALIVE_S);
  g_mqtt.setSocketTimeout(3);
  xTaskCreatePinnedToCore(netTask, "net", 8192, nullptr, 3, nullptr, 0);
}
