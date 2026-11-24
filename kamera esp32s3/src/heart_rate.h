#pragma once
#include <Arduino.h>

// MAX30102 (I2C 0x57) -> bpm. Task sampling ~100 Hz di core 0.
// finger=false (IR < HR_AMBANG_IR) -> bpm 0 (plan.md 5.5).
namespace heart_rate {

bool begin();      // false = sensor tidak terdeteksi (tidak fatal)
bool available();  // sensor terdeteksi dan task berjalan
int bpm();         // median HR_JENDELA detak terakhir; 0 bila belum terkunci / lepas
bool finger();     // sensor menempel di kulit
long ir();         // nilai IR mentah terakhir (untuk kalibrasi)

}  // namespace heart_rate
