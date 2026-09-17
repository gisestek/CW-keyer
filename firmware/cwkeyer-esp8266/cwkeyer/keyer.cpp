#include "keyer.h"

#include "config.h"
#include "feeder.h"
#include "morse.h"

namespace keyer {

// ---------------------------------------------------------------------------
// Jaettu tila. Rengaspuskurit ovat yksi kirjoittaja / yksi lukija:
//   elementit: loop kirjoittaa (head), keskeytys lukee (tail)
//   kaiku:     keskeytys kirjoittaa (head), loop lukee (tail)
// ---------------------------------------------------------------------------
static constexpr uint32_t RB_SIZE = 256;  // 2^n
static constexpr uint32_t RB_MASK = RB_SIZE - 1;
static morse::Element rb[RB_SIZE];
static volatile uint32_t rbHead = 0;
static volatile uint32_t rbTail = 0;

static constexpr uint32_t ECHO_SIZE = 128;
static constexpr uint32_t ECHO_MASK = ECHO_SIZE - 1;
static uint8_t echoBuf[ECHO_SIZE];
static volatile uint32_t echoHead = 0;
static volatile uint32_t echoTail = 0;

static volatile bool halted = false;   // true: keskeytys pitää avaimen ylhäällä ja tyhjentää jonon
static volatile uint8_t fault = FAULT_NONE;
static volatile bool isrBusy = false;
static volatile bool curKey = false;
static volatile uint32_t remaining = 0;
static volatile uint32_t keydownMs = 0;
static volatile uint32_t txMs = 0;
static volatile uint32_t silentMs = 0;

static volatile uint32_t limKeydown = KEYDOWN_MAX_MS;
static volatile uint32_t limTx = TX_MAX_MS;
static volatile uint32_t limHeartbeat = HEARTBEAT_MS;
static uint32_t limTune = TUNE_MAX_MS;

static Feeder<TEXT_QUEUE_SIZE> feeder;
static unsigned curWpm = DEFAULT_WPM;
static unsigned curWeight = DEFAULT_WEIGHT;
static morse::Timing timing = morse::makeTiming(DEFAULT_WPM, DEFAULT_WEIGHT);

static constexpr uint32_t KEY_MASK = 1UL << KEY_PIN;

// ---------------------------------------------------------------------------
// Keskeytyksen puoli (IRAM)
// ---------------------------------------------------------------------------
static inline IRAM_ATTR void hwKey(bool down) {
  bool level = down;
#if KEY_ACTIVE_LOW
  level = !down;
#endif
  if (level) GPOS = KEY_MASK; else GPOC = KEY_MASK;
  curKey = down;
}

static inline IRAM_ATTR void isrHalt(uint8_t code) {
  hwKey(false);
  remaining = 0;
  rbTail = rbHead;
  keydownMs = 0;
  txMs = 0;
  isrBusy = false;
  if (code != FAULT_NONE) {
    fault = code;
    halted = true;
  }
}

static IRAM_ATTR void onTick() {
  if (halted) {
    isrHalt(FAULT_NONE);
    return;
  }

  // Lataa seuraava elementti. 0 ms:n elementit ovat pelkkiä kaikumerkkejä.
  for (int guard = 0; guard < 8 && remaining == 0; ++guard) {
    if (rbTail == rbHead) {
      if (curKey) hwKey(false);
      isrBusy = false;
      break;
    }
    const morse::Element& e = rb[rbTail];
    rbTail = (rbTail + 1) & RB_MASK;
    if (e.echo) {
      uint32_t next = (echoHead + 1) & ECHO_MASK;
      if (next != echoTail) {
        echoBuf[echoHead] = e.echo;
        echoHead = next;
      }
    }
    if ((bool)e.key != curKey) hwKey(e.key);
    remaining = e.ms;
    isrBusy = true;
  }
  if (remaining) --remaining;

  // Turvarajat
  if (silentMs < 0xFFFFFFF0UL) ++silentMs;
  if (curKey) {
    if (++keydownMs > limKeydown) { isrHalt(FAULT_KEYDOWN_LIMIT); return; }
  } else {
    keydownMs = 0;
  }
  if (isrBusy) {
    if (++txMs > limTx) { isrHalt(FAULT_TX_LIMIT); return; }
    if (silentMs > limHeartbeat) { isrHalt(FAULT_HEARTBEAT); return; }
  } else {
    txMs = 0;
  }
}

// ---------------------------------------------------------------------------
// Pääsilmukan puoli
// ---------------------------------------------------------------------------
static uint32_t rbFree() {
  return RB_SIZE - 1 - ((rbHead - rbTail) & RB_MASK);
}

static void rbPush(const morse::Element& e) {
  rb[rbHead] = e;
  rbHead = (rbHead + 1) & RB_MASK;
}

void begin() {
  // Avain ylös ennen kuin pinni muuttuu lähdöksi.
#if KEY_ACTIVE_LOW
  digitalWrite(KEY_PIN, HIGH);
#else
  digitalWrite(KEY_PIN, LOW);
#endif
  pinMode(KEY_PIN, OUTPUT);
  hwKey(false);

  timer1_isr_init();
  timer1_attachInterrupt(onTick);
  timer1_enable(TIM_DIV16, TIM_EDGE, TIM_LOOP);  // 80 MHz / 16 = 5 MHz
  timer1_write(5000);                            // 5000 tikkiä = 1 ms
}

void service() {
  if (halted) return;
  morse::Element tmp[16];
  while (feeder.pending() && rbFree() >= 16) {
    int n = feeder.next(timing, tmp, 16);
    if (n < 0) break;
    for (int i = 0; i < n; ++i) rbPush(tmp[i]);
  }
}

size_t queueText(const char* s, size_t len) {
  txMs = 0;  // käyttäjän toimenpide (SR-03)
  silentMs = 0;
  return feeder.push(s, len);
}

bool tune(uint32_t ms) {
  if (busy()) return false;
  uint32_t cap = limTune;
  if (limKeydown > 200 && cap > limKeydown - 200) cap = limKeydown - 200;
  if (ms > cap) ms = cap;
  if (ms == 0) return false;
  txMs = 0;
  silentMs = 0;
  rbPush({(uint16_t)ms, 1, 0});
  rbPush({1, 0, 0});
  return true;
}

void stop() {
  halted = true;
  feeder.clear();
  delay(3);  // vähintään kaksi keskeytystä: avain ylös ja jono tyhjä
  hwKey(false);
  halted = false;
}

void hostActivity() { silentMs = 0; }

uint8_t takeFault() {
  uint8_t f = fault;
  if (f == FAULT_NONE) return f;
  feeder.clear();
  delay(3);
  fault = FAULT_NONE;
  halted = false;
  return f;
}

int popEcho() {
  if (echoTail == echoHead) return -1;
  uint8_t c = echoBuf[echoTail];
  echoTail = (echoTail + 1) & ECHO_MASK;
  return c;
}

void setWpm(unsigned w) {
  if (w < WPM_MIN) w = WPM_MIN;
  if (w > WPM_MAX) w = WPM_MAX;
  curWpm = w;
  timing = morse::makeTiming(curWpm, curWeight);
}

void setWeight(unsigned w) {
  if (w < 25) w = 25;
  if (w > 75) w = 75;
  curWeight = w;
  timing = morse::makeTiming(curWpm, curWeight);
}

unsigned wpm() { return curWpm; }
unsigned weight() { return curWeight; }

static uint32_t clampU(uint32_t v, uint32_t lo, uint32_t hi) {
  return v < lo ? lo : (v > hi ? hi : v);
}

void setLimits(const Limits& l) {
  limKeydown = clampU(l.keydownMs, 1000, KEYDOWN_MAX_MS);
  limTune = clampU(l.tuneMs, 500, TUNE_MAX_MS);
  limTx = clampU(l.txMs, 10000, TX_MAX_MS);
  limHeartbeat = clampU(l.heartbeatMs, 500, HEARTBEAT_MS);
}

Limits limits() { return {limKeydown, limTune, limTx, limHeartbeat}; }

bool busy() { return isrBusy || rbHead != rbTail || feeder.pending() > 0; }
bool keyDown() { return curKey; }
size_t pendingChars() { return feeder.pending(); }

const char* faultName(uint8_t f) {
  switch (f) {
    case FAULT_KEYDOWN_LIMIT: return "KEYDOWN_LIMIT";
    case FAULT_TX_LIMIT: return "TX_LIMIT";
    case FAULT_HEARTBEAT: return "HEARTBEAT_LOST";
    default: return "NONE";
  }
}

}  // namespace keyer
