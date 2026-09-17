// PC-testit: morse-ajoitus, tekstijono ja keskeytyksen turvarajat.
// g++ -std=c++17 -Ishim -I../cwkeyer test_keyer.cpp ../cwkeyer/keyer.cpp -o t && ./t
#include <cassert>
#include <cstdio>
#include <string>
#include <vector>
#include "Arduino.h"
#include "config.h"
#include "keyer.h"
#include "morse.h"
#include "feeder.h"

uint32_t gpio_out = 0;
GpioSet GPOS;
GpioClr GPOC;
void (*timer1_cb)() = nullptr;

// Simuloitu aika: yksi tikki = 1 ms
static uint64_t nowMs = 0;
static std::vector<std::pair<uint64_t, bool>> edges;  // (aika, avain alhaalla)
static bool lastKey = false;
static std::string echoed;

static bool relayOn() {
  bool pinHigh = gpio_out & (1u << KEY_PIN);
#if KEY_ACTIVE_LOW
  return !pinHigh;
#else
  return pinHigh;
#endif
}

static void tick() {
  timer1_cb();
  ++nowMs;
  bool k = relayOn();
  if (k != lastKey) { edges.push_back({nowMs, k}); lastKey = k; }
}
void delay(unsigned long ms) { for (unsigned long i = 0; i < ms; ++i) tick(); }

static void run(uint64_t ms, bool heartbeat = true) {
  for (uint64_t i = 0; i < ms; ++i) {
    keyer::service();
    int c;
    while ((c = keyer::popEcho()) >= 0) echoed += (char)c;
    if (heartbeat && (nowMs % 500) == 0) keyer::hostActivity();
    tick();
  }
}

static void reset() {
  keyer::stop();
  keyer::takeFault();
  run(10);
  edges.clear();
  echoed.clear();
}

static std::vector<uint64_t> onDurations() {
  std::vector<uint64_t> d;
  for (size_t i = 0; i + 1 < edges.size(); ++i)
    if (edges[i].second && !edges[i + 1].second) d.push_back(edges[i + 1].first - edges[i].first);
  return d;
}

int main() {
  int fails = 0;
  auto check = [&](bool ok, const char* what) {
    printf("%s  %s\n", ok ? "OK  " : "FAIL", what);
    if (!ok) ++fails;
  };

  // --- morse-ajoitus ---
  {
    auto t = morse::makeTiming(20, 50);
    check(t.dit == 60 && t.markDah == 180 && t.elemGap == 60, "20 WPM: dit 60, dah 180, väli 60 ms");
    auto w = morse::makeTiming(20, 60);
    check(w.markDit == 72 && w.elemGap == 48 && w.markDit + w.elemGap == 120, "painotus 60: piste pitenee, väli lyhenee, summa sama");
    morse::Element e[16];
    Feeder<64> f;
    const char* paris = "PARIS ";
    f.push(paris, strlen(paris));
    unsigned total = 0; int n;
    while ((n = f.next(t, e, 16)) >= 0) total += morse::totalMs(e, (size_t)n);
    check(total == 50 * 60, "\"PARIS \" = 50 yksikköä = 3000 ms");
    check(morse::pattern('?') && !morse::pattern('#'), "tuetut/ei tuetut merkit");
  }

  keyer::begin();
  check(!relayOn(), "käynnistys: rele ei vedä (SR-05)");

  // --- sähkötys ja kaiku ---
  reset();
  keyer::setWpm(20);
  keyer::queueText("PARIS ", 6);
  run(3200);
  auto on = onDurations();
  std::vector<uint64_t> expect = {60,180,180,60, 60,180, 60,180,60, 60,60, 60,60,60};
  check(on == expect, "PARIS: avainpulssien pituudet oikein");
  check(echoed == "PARIS ", "kaiku merkki kerrallaan: \"PARIS \"");
  check(!keyer::busy() && !relayOn(), "jonon jälkeen idle, avain ylhäällä");

  // --- prosign ---
  reset();
  keyer::queueText("<SK>", 4);
  run(2000);
  // S = ... , K = -.-  ilman merkkiväliä: SK:n välissä vain elementtiväli 60 ms
  bool gapOk = false;
  for (size_t i = 0; i + 1 < edges.size(); ++i)
    if (!edges[i].second && edges[i + 1].second && i >= 5 && i <= 6)
      gapOk = (edges[i + 1].first - edges[i].first) == 60;
  check(onDurations() == std::vector<uint64_t>({60,60,60,180,60,180}) && gapOk, "<SK>: kirjaimet ilman merkkiväliä");
  check(echoed == "<SK>", "prosignin kaiku \"<SK>\"");

  // --- STOP ---
  reset();
  keyer::queueText("TTTTTTTTTT", 10);
  run(90);  // keskellä ensimmäistä viivaa
  check(relayOn(), "STOP-testi: avain alhaalla ennen STOPia");
  uint64_t t0 = nowMs;
  keyer::stop();
  check(!relayOn() && nowMs - t0 <= 3, "STOP nostaa avaimen <= 3 ms (SR-01: < 50 ms)");
  run(1000);
  check(!keyer::busy() && edges.back().second == false && edges.size() == 2, "STOP tyhjentää jonon");

  // --- TUNE ---
  reset();
  check(keyer::tune(10000), "TUNE 10 s hyväksytään");
  run(12000);
  on = onDurations();
  check(on.size() == 1 && on[0] == 10000 && keyer::takeFault() == keyer::FAULT_NONE, "TUNE 10 s: yksi 10000 ms pulssi, ei vikaa");
  reset();
  keyer::tune(60000);
  run(15000);
  on = onDurations();
  check(on.size() == 1 && on[0] == 10000, "TUNE 60 s rajataan 10 s:iin");
  reset();
  keyer::queueText("E", 1);
  check(!keyer::tune(1000), "TUNE hylätään lähetyksen aikana");

  // --- heartbeat (SR-04) ---
  reset();
  uint64_t tHb = nowMs;
  keyer::queueText("CQ CQ CQ CQ CQ CQ CQ CQ CQ CQ CQ", 32);
  run(5000, false);  // isäntä hiljaa
  uint8_t f = keyer::takeFault();
  check(f == keyer::FAULT_HEARTBEAT, "heartbeat: hiljaisuus > 3 s -> HEARTBEAT_LOST");
  uint64_t tFault = 0;
  for (auto& e : edges) if (!e.second) tFault = e.first;
  check(!relayOn() && tFault > tHb && tFault - tHb <= 3002, "heartbeat: avain ylös viimeistään 3 s:n kohdalla");
  run(2000);
  check(!keyer::busy(), "heartbeat: jono tyhjennetty");

  // --- lähetyksen enimmäisaika (SR-03) ---
  reset();
  std::string longText(1000, 'E');
  keyer::queueText(longText.c_str(), longText.size());   // 1000 x E @20 WPM = 240 s
  run(125000, true);
  f = keyer::takeFault();
  check(f == keyer::FAULT_TX_LIMIT, "120 s ilman uutta komentoa -> TX_LIMIT");
  check(!relayOn() && !keyer::busy(), "TX_LIMIT: avain ylös, jono tyhjä");

  // --- avain alhaalla -raja (SR-02): 5 WPM, painotus 75 ---
  reset();
  keyer::Limits l = keyer::limits();
  l.keydownMs = 1000;
  keyer::setLimits(l);
  keyer::setWpm(5);
  keyer::setWeight(75);
  keyer::queueText("TTT", 3);   // viiva 840 ms < 1000 ms
  run(8000);
  check(keyer::takeFault() == keyer::FAULT_NONE, "pitkä viiva alle rajan ei laukaise");
  l.keydownMs = 500;           // alle minimin -> rajataan 1000:een
  keyer::setLimits(l);
  check(keyer::limits().keydownMs == 1000, "raja ei voi laskea alle 1000 ms");
  l.keydownMs = 99999;
  keyer::setLimits(l);
  check(keyer::limits().keydownMs == KEYDOWN_MAX_MS, "raja ei voi nousta yli config.h:n");

  // --- keskeytyksen avain alhaalla -varmistus: raja lasketaan kesken TUNEn ---
  reset();
  l.keydownMs = KEYDOWN_MAX_MS; keyer::setLimits(l);
  keyer::setWpm(20); keyer::setWeight(50);
  keyer::tune(10000);
  run(500);
  l.keydownMs = 1000; keyer::setLimits(l);
  run(3000);
  on = onDurations();
  check(keyer::takeFault() == keyer::FAULT_KEYDOWN_LIMIT && on.size() == 1 && on[0] <= 1001,
        "avain alhaalla > raja -> KEYDOWN_LIMIT, avain ylös rajan kohdalla");

  printf("\n%s (%d virhettä)\n", fails ? "EPÄONNISTUI" : "KAIKKI OK", fails);
  return fails ? 1 : 0;
}
