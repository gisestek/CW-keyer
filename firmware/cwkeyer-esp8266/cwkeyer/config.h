// CW keyer – ESP8266 firmware: asetukset
// Muuta vain tätä tiedostoa. Turvarajat ovat ylärajoja: PC-ohjelma voi
// laskea niitä ajon aikana, mutta ei nostaa (SR-02, SR-03, SR-04).
#pragma once
#include <Arduino.h>

#define FW_NAME    "cwkeyer-esp8266"
#define FW_VERSION "0.1.0"
#define PROTO_VERSION 1

// ---------------------------------------------------------------------------
// Avainlähtö
// ---------------------------------------------------------------------------
// Nykyinen proto: D1 (GPIO5) suoraan relekortin IN-nastaan.
// Testissä E3 rele toimi käänteisesti KEY_ACTIVE_LOW 1 -asetuksella, eli
// kortti vetää, kun IN on korkea (H-ohjaus). GPIO5 ei pulssita käynnistyksessä.
// Suositus: 10k D1 -> GND, jotta IN on varmasti matala käynnistyksen aikana.
#define KEY_PIN        D1
#define KEY_ACTIVE_LOW 0      // 0 = rele vetää, kun pinni on korkea

// ---------------------------------------------------------------------------
// CW-oletukset
// ---------------------------------------------------------------------------
#define DEFAULT_WPM     20
#define DEFAULT_WEIGHT  50    // 50 = normaali, 25..75
#define WPM_MIN         5
#define WPM_MAX         50

// ---------------------------------------------------------------------------
// Turvarajat (ylärajat)
// ---------------------------------------------------------------------------
#define KEYDOWN_MAX_MS   10500UL   // SR-02: yhtäjaksoinen avain alhaalla
#define TUNE_MAX_MS      10000UL   // FR-TX-08: TUNE enintään
#define TX_MAX_MS       120000UL   // SR-03: lähetys ilman uutta send/tune-komentoa
#define HEARTBEAT_MS      3000UL   // SR-04: hiljaisuus lähetyksen aikana -> STOP
#define TEXT_QUEUE_SIZE   1024     // merkkiä jonossa

// ---------------------------------------------------------------------------
// Verkko
// ---------------------------------------------------------------------------
#define HOSTNAME     "cwkeyer"          // -> cwkeyer.local
#define AP_NAME      "CWKeyer-Setup"    // varatukiasema, jos kotiverkkoon ei päästä
#define AP_PASSWORD  "cwkeyer73"        // vähintään 8 merkkiä
#define WS_PORT      81
#define PORTAL_TIMEOUT_S 0              // 0 = AP pysyy päällä, kunnes verkko asetettu

#define ENABLE_OTA   1
#define OTA_PASSWORD "change-me"        // vaihda; sama platformio.ini:hin
