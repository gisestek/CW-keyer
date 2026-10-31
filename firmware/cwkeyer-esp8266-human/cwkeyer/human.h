// CW keyer – human emulation timing model ("fist").
// Pure C++ without Arduino dependencies so it can be tested on a PC (test/).
//
// Every element duration is
//   dur = ideal * profile(element, char, position) * context * drift(t) * fatigue(t) * (1 + gauss(0, sigma))
// where all parameters are interpolated linearly from ideal (amount 0 %) to the
// style's value (100 %), and the probabilities of discrete events (errors,
// split letters, letters running together, hesitations) scale with amount².
// The unit is rescaled so that PARIS still takes 50 dits at the set WPM.
#pragma once
#include <cmath>
#include <cstddef>
#include <cstdint>

#include "morse.h"

namespace human {

enum Style : uint8_t { OLD_TIMER = 0, SELF_TAUGHT = 1, STRAIGHT_KEY = 2, RANDOM = 3, CUSTOM = 4, STYLE_COUNT = 5 };

// Parameter values at 100 %. Ideal values (0 %) are in idealParams().
struct Params {
  float ratio;         // dah/dit ratio before weighting (ideal 3)
  float ratioSpread;   // per-letter ratio offset +- (fixed per fist, ideal 0)
  float weight;        // marks longer by this fraction of a dit, taken from the following gap (ideal 0)
  float sigmaDit;      // relative jitter of dit marks
  float sigmaDah;      // relative jitter of dah marks
  float sigmaGap;      // relative jitter of gaps inside a character
  float sigmaSpace;    // relative jitter of character and word spaces
  float charSpace;     // character space multiplier (ideal 1)
  float wordSpace;     // word space multiplier (ideal 1)
  float wordTempo;     // per-word tempo sigma: phrase-like rhythm
  float driftSigma;    // slow tempo wander (Ornstein-Uhlenbeck), relative std
  float driftTau;      // its time constant in seconds (not interpolated)
  float fatigue;       // slowdown per minute of continuous sending
  float fatigueMax;    // fatigue cap
  float lastStretch;   // last mark of a character longer by this fraction ...
  float lastProb;      // ... with this probability
  float common;        // common words (CQ, DE, TU, 73, 5NN, the call after DE) faster by this fraction
  float rare;          // numbers and punctuation slower by this fraction
  float hesitate;      // probability of a pause before a number/punctuation in a word (x amount²)
  float hesitateDits;  // its length in dits
  float splitProb;     // probability that a gap inside a letter is too long (x amount²)
  float runProb;       // probability that a character space is too short (x amount²)
  float errorProb;     // probability per character of a dropped/extra dit (x amount²)
};

static constexpr size_t PARAM_COUNT = sizeof(Params) / sizeof(float);

struct Config {
  bool enabled = false;
  uint8_t style = OLD_TIMER;
  uint8_t amount = 50;  // 0..100 %
  Params p{};           // values at 100 %; filled from a preset, editable
};

const char* styleName(uint8_t s);        // "old_timer", "self_taught", "straight_key", "random", "custom"
int styleFromName(const char* name);     // -1 if unknown
Params idealParams();
Params preset(uint8_t style);            // OLD_TIMER, SELF_TAUGHT, STRAIGHT_KEY
Params randomParams(uint32_t seed);      // a random style with randomized values
void sanitize(Params& p);                // clamp every value to a sane range
void paramRange(size_t i, float& lo, float& hi);
const char* paramName(size_t i);         // JSON / web field names, PARAM_COUNT entries
inline float& param(Params& p, size_t i) { return reinterpret_cast<float*>(&p)[i]; }
inline float param(const Params& p, size_t i) { return reinterpret_cast<const float*>(&p)[i]; }

// Small fast PRNG (xorshift32) with uniform and Gaussian draws.
class Rng {
 public:
  explicit Rng(uint32_t seed = 0x1234567u) { reseed(seed); }
  void reseed(uint32_t s) { s_ = s ? s : 0x9E3779B9u; spare_ = false; }
  uint32_t next() {
    s_ ^= s_ << 13;
    s_ ^= s_ >> 17;
    s_ ^= s_ << 5;
    return s_;
  }
  float uniform() { return (next() >> 8) * (1.0f / 16777216.0f); }  // [0, 1)
  float gauss();  // N(0,1), clipped to +-3
 private:
  uint32_t s_;
  bool spare_ = false;
  float spareVal_ = 0;
};

class Fist {
 public:
  void configure(const Config& c);
  void setTiming(const morse::Timing& t);
  void seed(uint32_t s) { rng_.reseed(s); }
  bool enabled() const { return enabled_; }
  float amount() const { return a_; }
  const Params& effective() const { return e_; }  // interpolated values in use
  float unitScale() const { return k_; }

  // Word context. Called by the feeder when a new word starts.
  void beginWord(bool common);
  // Encodes one character (pattern of '.' and '-'). letter selects the per-letter
  // dah ratio. endGap: 0 = gap inside a prosign, 1 = normal character space.
  // hesitate: insert a pause before the character. Returns element count (<= 2*len+1).
  // counts: false for a mistaken attempt and the error sign (no ideal counterpart).
  size_t encode(const char* pattern, char letter, uint8_t echo, bool endGap, bool rare, bool hesitate,
                morse::Element* out, size_t max, bool counts = true);
  // Word space extra (on top of the character space), ms.
  uint16_t wordGap(bool counts = true);
  // Extra gap after a prosign '>', ms.
  uint16_t prosignEnd();

  bool rollError() { return rng_.uniform() < pError_; }
  bool rollHesitate() { return rng_.uniform() < pHesitate_; }
  uint32_t rand() { return rng_.next(); }

  // Rest: continuous-sending time is reset (fatigue recovers).
  void rest() { sentMs_ = 0; }
  float governor() const { return gov_; }
  float driftState() const { return x_; }

 private:
  uint16_t emit(float profileMs, float sigma, float minMs, float idealMs);
  float tempo() const;
  float fatigueFactor() const;
  void recompute();

  bool enabled_ = false;
  float a_ = 0;
  Params p100_{};
  Params e_{};  // effective (interpolated) values
  float pSplit_ = 0, pRun_ = 0, pError_ = 0, pHesitate_ = 0;
  float letterOffset_[64] = {};  // per-letter ratio offsets in [-1, 1] for ' '..'_'
  morse::Timing t_ = morse::makeTiming(20, 50);
  float k_ = 1;          // unit scale that keeps the average speed at the set WPM
  float x_ = 0;          // drift state (relative)
  float ctx_ = 1;        // context factor of the current character
  float word_ = 1;       // tempo factor of the current word
  bool common_ = false;  // current word is a common sequence
  float sentMs_ = 0;     // continuous sending time
  // Speed keeper: like an operator who keeps the set speed, the tempo is nudged so
  // that over ~30 s the sent time matches the ideal time (fatigue excluded).
  float idealSum_ = 0, naturalSum_ = 0, gov_ = 1;
  Rng rng_;
};

// Dropped or extra dit (H<->S, U<->V ...). Writes the new pattern to out (>= 9 bytes).
// Returns false if no change was possible.
bool mutatePattern(const char* in, char* out, uint32_t r);

// Common sequences sent from muscle memory.
bool isCommonWord(const char* w, size_t n);
inline bool isRareChar(char c) { return !(c >= 'A' && c <= 'Z') && !(c >= 'a' && c <= 'z'); }

}  // namespace human
