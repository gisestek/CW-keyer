#include "settings_store.h"

#include <EEPROM.h>

namespace store {

namespace {

constexpr uint32_t MAGIC = 0x48554D31;  // "HUM1"
constexpr uint16_t VERSION = 1;
constexpr size_t EEPROM_BYTES = 256;

struct Blob {
  uint32_t magic;
  uint16_t version;
  uint16_t size;
  human::Config cfg;
  uint32_t crc;
};
static_assert(sizeof(Blob) <= EEPROM_BYTES, "settings do not fit");

uint32_t crc32(const uint8_t* d, size_t n) {
  uint32_t c = 0xFFFFFFFFu;
  for (size_t i = 0; i < n; ++i) {
    c ^= d[i];
    for (int k = 0; k < 8; ++k) c = (c >> 1) ^ (0xEDB88320u & (0u - (c & 1u)));
  }
  return ~c;
}

}  // namespace

bool load(human::Config& c) {
  EEPROM.begin(EEPROM_BYTES);
  Blob b;
  EEPROM.get(0, b);
  EEPROM.end();
  if (b.magic != MAGIC || b.version != VERSION || b.size != sizeof(human::Config)) return false;
  if (b.crc != crc32(reinterpret_cast<const uint8_t*>(&b.cfg), sizeof(b.cfg))) return false;
  c = b.cfg;
  human::sanitize(c.p);
  if (c.amount > 100) c.amount = 100;
  if (c.style >= human::STYLE_COUNT) c.style = human::CUSTOM;
  return true;
}

bool save(const human::Config& c) {
  Blob b{};
  b.magic = MAGIC;
  b.version = VERSION;
  b.size = sizeof(human::Config);
  b.cfg = c;
  b.crc = crc32(reinterpret_cast<const uint8_t*>(&b.cfg), sizeof(b.cfg));
  EEPROM.begin(EEPROM_BYTES);
  EEPROM.put(0, b);
  bool ok = EEPROM.commit();
  EEPROM.end();
  return ok;
}

}  // namespace store
