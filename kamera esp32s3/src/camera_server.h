#pragma once
#include <Arduino.h>

// Kamera + server HTTP MJPEG di port STREAM_PORT (plan.md 4.1).
//   GET /stream  -> multipart/x-mixed-replace MJPEG (satu klien: koneksi terbaru menggantikan yang lama)
//   GET /capture -> satu JPEG (untuk uji)
namespace camera_server {

bool initCamera();               // esp_camera_init; false = kamera tidak terdeteksi
bool startHttp();                // jalankan esp_http_server
void lock();                     // mutex akses sensor/frame buffer (dipakai juga oleh tuning)
void unlock();
void restartStream();            // akhiri stream aktif -> klien (SBC) menyambung ulang
void setStreamEnabled(bool on);  // glasses/cmd {"stream": false} -> /stream menjawab 503
bool streamEnabled();
bool cameraOk();                 // false bila frame gagal diambil berulang kali
float streamFps();
const char *sensorName();        // OV2640 / OV3660 / OV5640 / unknown

}  // namespace camera_server
