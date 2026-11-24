#include "camera_tuning.h"

#include <ArduinoJson.h>
#include <Preferences.h>
#include <esp_camera.h>

#include "camera_server.h"

// Nama parameter dan rentang mengikuti plan.md 5.6 (driver esp32-camera, OV2640).
// Kunci JSON = kunci NVS (maks 15 karakter).
enum Kind : uint8_t { K_INT, K_BOOL, K_FRAMESIZE };

struct Spec {
  const char *key;
  Kind kind;
  int16_t lo, hi, def;
};

static const Spec SPECS[] = {
    {"framesize", K_FRAMESIZE, 0, 4, 1},  // indeks ke FRAMESIZE_NAMES, default QVGA
    {"quality", K_INT, 4, 63, 12},
    {"brightness", K_INT, -2, 2, 0},
    {"contrast", K_INT, -2, 2, 0},
    {"saturation", K_INT, -2, 2, 0},
    {"sharpness", K_INT, -2, 2, 0},
    {"awb", K_BOOL, 0, 1, 1},
    {"wb_mode", K_INT, 0, 4, 0},
    {"aec", K_BOOL, 0, 1, 1},
    {"aec_value", K_INT, 0, 1200, 300},
    {"ae_level", K_INT, -2, 2, 0},
    {"agc", K_BOOL, 0, 1, 1},
    {"agc_gain", K_INT, 0, 30, 0},
    {"gainceiling", K_INT, 0, 6, 2},
    {"hmirror", K_BOOL, 0, 1, 0},
    {"vflip", K_BOOL, 0, 1, 0},
    {"lenc", K_BOOL, 0, 1, 1},
    {"bpc", K_BOOL, 0, 1, 0},
    {"wpc", K_BOOL, 0, 1, 1},
    {"raw_gma", K_BOOL, 0, 1, 1},
    {"dcw", K_BOOL, 0, 1, 1},
};
static const size_t N_SPECS = sizeof(SPECS) / sizeof(SPECS[0]);

static const char *FRAMESIZE_NAMES[] = {"QQVGA", "QVGA", "CIF", "VGA", "SVGA"};
static const framesize_t FRAMESIZE_VALUES[] = {FRAMESIZE_QQVGA, FRAMESIZE_QVGA, FRAMESIZE_CIF,
                                               FRAMESIZE_VGA, FRAMESIZE_SVGA};

static int16_t g_values[N_SPECS];
static String g_errors = "{}";  // JSON objek error dari set terakhir
static Preferences g_prefs;

// Panggil setter sensor yang sesuai. Return 0 bila sukses.
static int applyOne(sensor_t *s, size_t i, int v) {
  const char *k = SPECS[i].key;
#define CALL(fn, val) return (s->fn ? s->fn(s, (val)) : -1)
  if (!strcmp(k, "framesize")) CALL(set_framesize, FRAMESIZE_VALUES[v]);
  if (!strcmp(k, "quality")) CALL(set_quality, v);
  if (!strcmp(k, "brightness")) CALL(set_brightness, v);
  if (!strcmp(k, "contrast")) CALL(set_contrast, v);
  if (!strcmp(k, "saturation")) CALL(set_saturation, v);
  if (!strcmp(k, "sharpness")) CALL(set_sharpness, v);
  if (!strcmp(k, "awb")) CALL(set_whitebal, v);
  if (!strcmp(k, "wb_mode")) CALL(set_wb_mode, v);
  if (!strcmp(k, "aec")) CALL(set_exposure_ctrl, v);
  if (!strcmp(k, "aec_value")) CALL(set_aec_value, v);
  if (!strcmp(k, "ae_level")) CALL(set_ae_level, v);
  if (!strcmp(k, "agc")) CALL(set_gain_ctrl, v);
  if (!strcmp(k, "agc_gain")) CALL(set_agc_gain, v);
  if (!strcmp(k, "gainceiling")) CALL(set_gainceiling, (gainceiling_t)v);
  if (!strcmp(k, "hmirror")) CALL(set_hmirror, v);
  if (!strcmp(k, "vflip")) CALL(set_vflip, v);
  if (!strcmp(k, "lenc")) CALL(set_lenc, v);
  if (!strcmp(k, "bpc")) CALL(set_bpc, v);
  if (!strcmp(k, "wpc")) CALL(set_wpc, v);
  if (!strcmp(k, "raw_gma")) CALL(set_raw_gma, v);
  if (!strcmp(k, "dcw")) CALL(set_dcw, v);
#undef CALL
  return -1;
}

void camera_tuning::begin() {
  g_prefs.begin("cam", false);
  for (size_t i = 0; i < N_SPECS; i++) {
    int v = g_prefs.getShort(SPECS[i].key, SPECS[i].def);
    if (v < SPECS[i].lo || v > SPECS[i].hi) v = SPECS[i].def;  // NVS rusak / versi lama
    g_values[i] = v;
  }
  sensor_t *s = esp_camera_sensor_get();
  if (!s) return;
  camera_server::lock();
  for (size_t i = 0; i < N_SPECS; i++) {
    if (applyOne(s, i, g_values[i]) != 0)
      Serial.printf("[tuning] %s=%d tidak didukung sensor ini\n", SPECS[i].key, g_values[i]);
  }
  camera_server::unlock();
  Serial.printf("[tuning] parameter dimuat dari NVS (framesize %s)\n", FRAMESIZE_NAMES[g_values[0]]);
}

// Validasi satu nilai JSON. Return true + out bila valid, false + pesan bila ditolak.
static bool parseValue(const Spec &sp, JsonVariantConst v, int &out, const char *&err) {
  if (sp.kind == K_FRAMESIZE) {
    if (!v.is<const char *>()) {
      err = "harus nama: QQVGA/QVGA/CIF/VGA/SVGA";
      return false;
    }
    const char *name = v.as<const char *>();
    for (int i = 0; i <= sp.hi; i++) {
      if (!strcasecmp(name, FRAMESIZE_NAMES[i])) {
        out = i;
        return true;
      }
    }
    err = "framesize tidak dikenal";
    return false;
  }
  if (v.is<bool>()) {
    if (sp.kind != K_BOOL) {
      err = "harus angka";
      return false;
    }
    out = v.as<bool>() ? 1 : 0;
    return true;
  }
  if (!v.is<int>()) {
    err = "harus angka";
    return false;
  }
  int x = v.as<int>();
  if (x < sp.lo || x > sp.hi) {
    err = "di luar rentang";
    return false;
  }
  out = x;
  return true;
}

bool camera_tuning::applyJson(const char *json, size_t len, bool &framesizeChanged) {
  framesizeChanged = false;
  JsonDocument doc;
  if (deserializeJson(doc, json, len) || !doc.is<JsonObject>()) {
    g_errors = "{\"_\":\"JSON tidak valid\"}";
    return false;
  }

  JsonDocument errs;
  JsonObject eo = errs.to<JsonObject>();
  sensor_t *s = esp_camera_sensor_get();

  for (JsonPairConst kv : doc.as<JsonObjectConst>()) {
    const char *key = kv.key().c_str();
    size_t i = 0;
    while (i < N_SPECS && strcmp(SPECS[i].key, key)) i++;
    if (i == N_SPECS) {
      eo[key] = "parameter tidak dikenal";
      continue;
    }
    int v;
    const char *err = nullptr;
    if (!parseValue(SPECS[i], kv.value(), v, err)) {
      eo[key] = err;
      continue;
    }
    if (v == g_values[i]) continue;

    camera_server::lock();
    int rc = s ? applyOne(s, i, v) : -1;
    camera_server::unlock();
    if (rc != 0) {
      eo[key] = "tidak didukung sensor";
      continue;
    }
    if (SPECS[i].kind == K_FRAMESIZE) framesizeChanged = true;
    g_values[i] = v;
    g_prefs.putShort(SPECS[i].key, v);
    Serial.printf("[tuning] %s = %d\n", key, v);
  }

  g_errors = "";
  serializeJson(errs, g_errors);
  return true;
}

String camera_tuning::stateJson() {
  JsonDocument doc;
  for (size_t i = 0; i < N_SPECS; i++) {
    if (SPECS[i].kind == K_FRAMESIZE)
      doc[SPECS[i].key] = FRAMESIZE_NAMES[g_values[i]];
    else
      doc[SPECS[i].key] = g_values[i];
  }
  doc["sensor"] = camera_server::sensorName();
  JsonDocument errs;
  deserializeJson(errs, g_errors);
  doc["errors"] = errs;
  String out;
  serializeJson(doc, out);
  return out;
}
