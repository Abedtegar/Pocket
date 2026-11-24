#include "heart_rate.h"

#include <MAX30105.h>
#include <Wire.h>
#include <heartRate.h>

#include <atomic>

#include "config.h"

// Kalau penolakan "interval ganda" terjadi berkali-kali berturut-turut, asumsinya
// detak memang berubah, bukan denyut terlewat. Tanpa jalan keluar ini median lama
// bisa terkunci selamanya.
static const int TOLAK_BERUNTUN_MAKS = 3;

static MAX30105 g_sensor;
static bool g_available = false;
static std::atomic<bool> g_finger{false};
static std::atomic<int> g_bpm{0};
static std::atomic<long> g_ir{0};

// Jendela median; g_pos = slot tulis berikutnya. Hanya disentuh hrTask.
static uint8_t g_rates[HR_JENDELA];
static int g_n = 0;
static int g_pos = 0;
static int g_tolak_beruntun = 0;
static uint32_t g_beat_terakhir = 0;

bool heart_rate::available() { return g_available; }
int heart_rate::bpm() { return g_available && g_finger ? g_bpm.load() : 0; }
bool heart_rate::finger() { return g_available && g_finger; }
long heart_rate::ir() { return g_ir; }

// Median, bukan rata-rata: satu interval meleset (biasanya denyut terlewat) hanya
// menggeser urutan satu langkah, tidak menarik hasil seperti rata-rata.
static int median() {
  uint8_t t[HR_JENDELA];
  memcpy(t, g_rates, g_n);
  for (int i = 1; i < g_n; i++) {
    uint8_t v = t[i];
    int j = i - 1;
    while (j >= 0 && t[j] > v) {
      t[j + 1] = t[j];
      j--;
    }
    t[j + 1] = v;
  }
  return t[g_n / 2];
}

static void resetHitungan() {
  g_n = 0;
  g_pos = 0;
  g_tolak_beruntun = 0;
  g_bpm = 0;
}

static void prosesSampel(long ir) {
  g_ir = ir;

  if (ir < HR_AMBANG_IR) {
    if (g_finger) {
      Serial.println("[hr] sensor lepas");
      resetHitungan();
    }
    g_finger = false;
    return;
  }
  if (!g_finger) {
    Serial.println("[hr] sensor menempel");
    g_beat_terakhir = millis();
    g_finger = true;
  }

  if (!checkForBeat(ir)) return;

  uint32_t now = millis();
  uint32_t delta = now - g_beat_terakhir;
  g_beat_terakhir = now;
  if (delta == 0) return;

  int nilai = (int)(60000UL / delta);
  if (nilai < HR_BPM_VALID_MIN || nilai > HR_BPM_VALID_MAX) return;

#if HR_TOLAK_GANDA
  // Satu denyut terlewat -> interval 2x -> nilai ~setengah median. Dibuang.
  if (g_n >= 3) {
    int med = median();
    int dua = nilai * 2;
    if (dua >= med * 85 / 100 && dua <= med * 115 / 100 && g_tolak_beruntun < TOLAK_BERUNTUN_MAKS) {
      g_tolak_beruntun++;
      return;
    }
  }
#endif
  g_tolak_beruntun = 0;

  g_rates[g_pos] = (uint8_t)nilai;  // <= HR_BPM_VALID_MAX (220), muat di uint8_t
  g_pos = (g_pos + 1) % HR_JENDELA;
  if (g_n < HR_JENDELA) g_n++;
  if (g_n >= 3) g_bpm = median();  // median 3 titik sudah tahan satu pencilan
}

static void hrTask(void *) {
  for (;;) {
    // check() menarik SEMUA sampel baru dari FIFO sensor; dikuras satu per satu
    // agar tidak ada puncak denyut yang terlewat.
    g_sensor.check();
    while (g_sensor.available()) {
      prosesSampel(g_sensor.getFIFOIR());
      g_sensor.nextSample();
    }
    vTaskDelay(pdMS_TO_TICKS(10));  // ~100 Hz
  }
}

bool heart_rate::begin() {
  // Bus Wire (I2C port 0). Kamera memakai SCCB GPIO39/40 lewat driver sendiri.
  Wire.begin(HR_SDA_PIN, HR_SCL_PIN);
  if (!g_sensor.begin(Wire, I2C_SPEED_STANDARD)) {
    Serial.printf("[hr] MAX30102 tidak terdeteksi (SDA=%d SCL=%d) - heart rate nonaktif\n",
                  HR_SDA_PIN, HR_SCL_PIN);
    return false;
  }
  // ledMode 2 = Merah + IR (MAX30102 tidak punya LED hijau).
  g_sensor.setup(HR_LED_ARUS, HR_SAMPLE_AVG, 2, 400, 411, 4096);
  g_sensor.setPulseAmplitudeRed(0x0A);  // merah redup: penanda hidup saja

  if (xTaskCreatePinnedToCore(hrTask, "hr", 4096, nullptr, 2, nullptr, 0) != pdPASS) {
    Serial.println("[hr] task gagal dibuat");
    return false;
  }
  g_available = true;
  Serial.printf("[hr] MAX30102 OK - %d sampel/detik, median %d detak\n", 400 / HR_SAMPLE_AVG, HR_JENDELA);
  return true;
}
