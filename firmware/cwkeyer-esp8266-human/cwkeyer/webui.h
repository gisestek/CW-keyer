// CW keyer – web settings page (human emulation), port HTTP_PORT.
#pragma once

namespace webui {

bool begin();  // call once the station WiFi is up and the WiFiManager portal is not running
void loop();   // call in loop(): serves requests, saves settings when the keyer is idle

}  // namespace webui
