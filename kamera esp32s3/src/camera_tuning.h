#pragma once
#include <Arduino.h>

// Tuning parameter sensor kamera lapis 1 (plan.md 5.6).
// Pesan glasses/camera/set boleh sebagian; nilai di luar rentang ditolak dan dilaporkan
// di field "errors" pada glasses/camera/state. Nilai disimpan di NVS (bertahan reboot).
namespace camera_tuning {

void begin();  // muat NVS lalu terapkan ke sensor (panggil setelah camera_server::initCamera)

// Terapkan JSON sebagian. framesizeChanged = true bila resolusi berubah (stream perlu restart).
// Return false bila JSON tidak bisa diparse.
bool applyJson(const char *json, size_t len, bool &framesizeChanged);

String stateJson();  // seluruh parameter aktif + sensor + errors dari set terakhir

}  // namespace camera_tuning
