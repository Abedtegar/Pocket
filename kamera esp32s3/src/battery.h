#pragma once
#include <Arduino.h>

// Tegangan baterai LiPo kacamata lewat pembagi tegangan ke BATTERY_PIN.
namespace battery {

void begin();
uint32_t millivolts();  // 0 bila BATTERY_ENABLED = 0

}  // namespace battery
