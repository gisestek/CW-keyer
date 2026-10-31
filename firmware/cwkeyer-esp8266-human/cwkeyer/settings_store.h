// CW keyer – human emulation settings in flash (EEPROM emulation).
#pragma once
#include "human.h"

namespace store {

bool load(human::Config& c);        // false if nothing valid is stored
bool save(const human::Config& c);  // written only when the settings page saves

}  // namespace store
