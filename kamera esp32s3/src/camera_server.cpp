#include "camera_server.h"

#include <esp_camera.h>
#include <esp_http_server.h>

#include <atomic>

#include "camera_pins.h"
#include "config.h"

#define PART_BOUNDARY "guardianframe"
static const char *STREAM_CONTENT_TYPE = "multipart/x-mixed-replace;boundary=" PART_BOUNDARY;
static const char *STREAM_BOUNDARY = "\r\n--" PART_BOUNDARY "\r\n";
static const char *STREAM_PART = "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

static SemaphoreHandle_t g_cam_lock = nullptr;
static httpd_handle_t g_httpd = nullptr;

// Setiap koneksi stream baru / restartStream() menaikkan generasi; handler yang
// generasinya sudah usang berhenti sendiri. Dengan begitu hanya ada satu klien
// aktif, dan koneksi SBC yang "menggantung" tidak menghalangi sambung ulang.
static std::atomic<uint32_t> g_generation{0};
static std::atomic<bool> g_enabled{true};
static std::atomic<bool> g_cam_ok{false};
static std::atomic<float> g_fps{0};
static const char *g_sensor_name = "unknown";

void camera_server::lock() { xSemaphoreTake(g_cam_lock, portMAX_DELAY); }
void camera_server::unlock() { xSemaphoreGive(g_cam_lock); }
void camera_server::restartStream() { g_generation++; }
bool camera_server::streamEnabled() { return g_enabled; }
bool camera_server::cameraOk() { return g_cam_ok; }
float camera_server::streamFps() { return g_fps; }
const char *camera_server::sensorName() { return g_sensor_name; }

void camera_server::setStreamEnabled(bool on) {
  g_enabled = on;
  if (!on) g_generation++;
  Serial.printf("[cam] stream %s\n", on ? "diaktifkan" : "dinonaktifkan");
}

// ------------------------------------------------------------------ kamera
bool camera_server::initCamera() {
  if (!g_cam_lock) g_cam_lock = xSemaphoreCreateMutex();

  camera_config_t c = {};
  c.ledc_channel = LEDC_CHANNEL_0;
  c.ledc_timer = LEDC_TIMER_0;
  c.pin_d0 = Y2_GPIO_NUM;
  c.pin_d1 = Y3_GPIO_NUM;
  c.pin_d2 = Y4_GPIO_NUM;
  c.pin_d3 = Y5_GPIO_NUM;
  c.pin_d4 = Y6_GPIO_NUM;
  c.pin_d5 = Y7_GPIO_NUM;
  c.pin_d6 = Y8_GPIO_NUM;
  c.pin_d7 = Y9_GPIO_NUM;
  c.pin_xclk = XCLK_GPIO_NUM;
  c.pin_pclk = PCLK_GPIO_NUM;
  c.pin_vsync = VSYNC_GPIO_NUM;
  c.pin_href = HREF_GPIO_NUM;
  c.pin_sccb_sda = SIOD_GPIO_NUM;
  c.pin_sccb_scl = SIOC_GPIO_NUM;
  c.pin_pwdn = PWDN_GPIO_NUM;
  c.pin_reset = RESET_GPIO_NUM;
  c.xclk_freq_hz = CAMERA_XCLK_HZ;
  c.pixel_format = PIXFORMAT_JPEG;
  c.jpeg_quality = 12;

  if (psramFound()) {
    c.frame_size = CAMERA_MAX_FRAMESIZE;  // buffer cukup untuk resolusi terbesar
    c.fb_count = 2;
    c.fb_location = CAMERA_FB_IN_PSRAM;
    c.grab_mode = CAMERA_GRAB_LATEST;     // selalu frame terbaru, tidak menumpuk
  } else {
    Serial.println("[cam] PSRAM tidak terdeteksi - maksimal QVGA, 1 buffer");
    c.frame_size = FRAMESIZE_QVGA;
    c.fb_count = 1;
    c.fb_location = CAMERA_FB_IN_DRAM;
    c.grab_mode = CAMERA_GRAB_WHEN_EMPTY;
  }

  esp_err_t err = esp_camera_init(&c);
  if (err != ESP_OK) {
    Serial.printf("[cam] init GAGAL (0x%x)\n", err);
    return false;
  }

  sensor_t *s = esp_camera_sensor_get();
  switch (s->id.PID) {
    case OV2640_PID: g_sensor_name = "OV2640"; break;
    case OV3660_PID: g_sensor_name = "OV3660"; break;
    case OV5640_PID: g_sensor_name = "OV5640"; break;
    default: g_sensor_name = "unknown"; break;
  }
  s->set_framesize(s, FRAMESIZE_QVGA);  // default; preset NVS diterapkan camera_tuning
  g_cam_ok = true;
  Serial.printf("[cam] sensor %s OK\n", g_sensor_name);
  return true;
}

// ------------------------------------------------------------------ handler
static esp_err_t captureHandler(httpd_req_t *req) {
  camera_server::lock();
  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) {
    camera_server::unlock();
    g_cam_ok = false;
    httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "kamera tidak merespons");
    return ESP_FAIL;
  }
  g_cam_ok = true;
  httpd_resp_set_type(req, "image/jpeg");
  httpd_resp_set_hdr(req, "Cache-Control", "no-store");
  esp_err_t res = httpd_resp_send(req, (const char *)fb->buf, fb->len);
  esp_camera_fb_return(fb);
  camera_server::unlock();
  return res;
}

static esp_err_t streamHandler(httpd_req_t *req) {
  if (!g_enabled) {
    httpd_resp_set_status(req, "503 Service Unavailable");
    httpd_resp_sendstr(req, "stream dinonaktifkan (glasses/cmd)");
    return ESP_OK;
  }
  esp_err_t res = httpd_resp_set_type(req, STREAM_CONTENT_TYPE);
  if (res != ESP_OK) return res;
  httpd_resp_set_hdr(req, "Cache-Control", "no-store");

  const uint32_t gen = ++g_generation;  // klien lama (jika ada) akan berhenti
  char part[64];
  uint32_t frames = 0, gagal = 0;
  uint32_t t_fps = millis();
  Serial.println("[cam] klien stream terhubung");

  while (g_enabled && gen == g_generation) {
    camera_server::lock();
    camera_fb_t *fb = esp_camera_fb_get();
    camera_server::unlock();
    if (!fb) {
      if (++gagal >= 10) {
        g_cam_ok = false;
        res = ESP_FAIL;
        break;
      }
      vTaskDelay(pdMS_TO_TICKS(20));
      continue;
    }
    gagal = 0;
    g_cam_ok = true;

    size_t hlen = snprintf(part, sizeof(part), STREAM_PART, fb->len);
    res = httpd_resp_send_chunk(req, STREAM_BOUNDARY, strlen(STREAM_BOUNDARY));
    if (res == ESP_OK) res = httpd_resp_send_chunk(req, part, hlen);
    if (res == ESP_OK) res = httpd_resp_send_chunk(req, (const char *)fb->buf, fb->len);
    esp_camera_fb_return(fb);
    if (res != ESP_OK) break;  // klien menutup koneksi

    frames++;
    uint32_t now = millis();
    if (now - t_fps >= 2000) {
      g_fps = frames * 1000.0f / (now - t_fps);
      frames = 0;
      t_fps = now;
    }
  }
  if (res == ESP_OK) httpd_resp_send_chunk(req, NULL, 0);
  if (gen == g_generation) g_fps = 0;
  Serial.println("[cam] stream berakhir");
  return res;
}

static esp_err_t rootHandler(httpd_req_t *req) {
  httpd_resp_set_type(req, "text/plain");
  return httpd_resp_sendstr(req, "Guardian glasses " FW_VERSION "\n/stream  MJPEG\n/capture JPEG\n");
}

bool camera_server::startHttp() {
  httpd_config_t cfg = HTTPD_DEFAULT_CONFIG();
  cfg.server_port = STREAM_PORT;
  cfg.ctrl_port = 32768 + STREAM_PORT;
  cfg.core_id = 1;              // core 1: stream; core 0: WiFi/MQTT/HR
  cfg.stack_size = 8192;
  cfg.max_open_sockets = 4;
  cfg.lru_purge_enable = true;  // buang soket lama kalau penuh
  cfg.send_wait_timeout = 5;
  cfg.recv_wait_timeout = 5;

  if (httpd_start(&g_httpd, &cfg) != ESP_OK) {
    Serial.println("[cam] httpd gagal start");
    return false;
  }
  httpd_uri_t stream = {"/stream", HTTP_GET, streamHandler, nullptr};
  httpd_uri_t capture = {"/capture", HTTP_GET, captureHandler, nullptr};
  httpd_uri_t root = {"/", HTTP_GET, rootHandler, nullptr};
  httpd_register_uri_handler(g_httpd, &stream);
  httpd_register_uri_handler(g_httpd, &capture);
  httpd_register_uri_handler(g_httpd, &root);
  Serial.printf("[cam] HTTP di port %d\n", STREAM_PORT);
  return true;
}
