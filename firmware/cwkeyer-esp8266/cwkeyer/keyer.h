// CW keyer – avainnusmoottori.
// Ajoitus ja turvarajat pyörivät 1 ms:n laitteistoajastimen keskeytyksessä
// (timer1), joten ne toimivat, vaikka WiFi tai pääsilmukka jumittuisi.
#pragma once
#include <Arduino.h>

namespace keyer {

enum Fault : uint8_t {
  FAULT_NONE = 0,
  FAULT_KEYDOWN_LIMIT,  // SR-02
  FAULT_TX_LIMIT,       // SR-03
  FAULT_HEARTBEAT,      // SR-04
};

const char* faultName(uint8_t f);

struct Limits {
  uint32_t keydownMs;
  uint32_t tuneMs;
  uint32_t txMs;
  uint32_t heartbeatMs;
};

void begin();                 // kutsu setupin ensimmäisenä: avain ylös
void service();               // kutsu loopissa: muuntaa tekstiä elementeiksi

size_t queueText(const char* s, size_t len);  // palauttaa hyväksytyt merkit
bool tune(uint32_t ms);       // false, jos lähetys käynnissä
void stop();                  // tyhjennä jono, avain ylös (< 2 ms)

void hostActivity();          // mikä tahansa viesti ohjaavalta isännältä
uint8_t takeFault();          // palauttaa ja kuittaa keskeytyksen asettaman vian
int popEcho();                // seuraava kaiutettava merkki tai -1

void setWpm(unsigned wpm);
void setWeight(unsigned weight);
unsigned wpm();
unsigned weight();

void setLimits(const Limits& l);   // rajataan config.h:n ylärajoihin
Limits limits();

bool busy();
bool keyDown();
size_t pendingChars();

}  // namespace keyer
