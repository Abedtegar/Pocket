#include "battery.h"

#include "config.h"

// Satu pembacaan ADC berderau puluhan mV; 16 sampel cukup meratakan (~1 ms).
static const int SAMPEL = 16;

void battery::begin() {
#if BATTERY_ENABLED
  // Redaman 11 dB: jangkauan ADC ~3,1 V (pin menerima setengah tegangan baterai).
  analogSetPinAttenuation((uint8_t)BATTERY_PIN, ADC_11db);
  Serial.printf("[batt] ADC GPIO%d, divider %.0f/%.0f\n", BATTERY_PIN, BATTERY_R1, BATTERY_R2);
#else
  Serial.println("[batt] nonaktif (BATTERY_ENABLED 0) - batt_mv dikirim 0");
#endif
}

uint32_t battery::millivolts() {
#if BATTERY_ENABLED
  uint32_t total = 0;
  for (int i = 0; i < SAMPEL; i++) total += analogReadMilliVolts((uint8_t)BATTERY_PIN);
  // analogReadMilliVolts() sudah memakai kalibrasi eFuse pabrik.
  float v_pin = (float)total / SAMPEL;
  return (uint32_t)(v_pin * (BATTERY_R1 + BATTERY_R2) / BATTERY_R2);
#else
  return 0;
#endif
}
