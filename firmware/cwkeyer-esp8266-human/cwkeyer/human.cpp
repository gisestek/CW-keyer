#include "human.h"

#include <cstring>

namespace human {

namespace {

const char* const kStyleNames[STYLE_COUNT] = {"old_timer", "self_taught", "straight_key", "random", "custom"};

const char* const kParamNames[PARAM_COUNT] = {
    "ratio",      "ratio_spread", "weight",     "sigma_dit",  "sigma_dah", "sigma_gap",
    "sigma_space", "char_space",  "word_space", "word_tempo", "drift",     "drift_tau",
    "fatigue",    "fatigue_max",  "last_stretch", "last_prob", "common",   "rare",
    "hesitate",   "hesitate_dits", "split",     "run",        "error"};

static_assert(sizeof(kParamNames) / sizeof(kParamNames[0]) == PARAM_COUNT, "parameter names");

inline float clampf(float v, float lo, float hi) { return v < lo ? lo : (v > hi ? hi : v); }

uint32_t fnv1a(const void* data, size_t n) {
  const uint8_t* b = static_cast<const uint8_t*>(data);
  uint32_t h = 2166136261u;
  for (size_t i = 0; i < n; ++i) {
    h ^= b[i];
    h *= 16777619u;
  }
  return h;
}

inline char upper(char c) { return (c >= 'a' && c <= 'z') ? (char)(c - 'a' + 'A') : c; }

}  // namespace

const char* styleName(uint8_t s) { return s < STYLE_COUNT ? kStyleNames[s] : "custom"; }

int styleFromName(const char* name) {
  if (!name) return -1;
  for (int i = 0; i < STYLE_COUNT; ++i)
    if (!strcmp(name, kStyleNames[i])) return i;
  return -1;
}

const char* paramName(size_t i) { return i < PARAM_COUNT ? kParamNames[i] : ""; }

void paramRange(size_t i, float& lo, float& hi) {
  static const float kLo[PARAM_COUNT] = {2.0f, 0, 0, 0, 0, 0, 0, 0.6f, 0.6f, 0, 0, 0.5f, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0};
  static const float kHi[PARAM_COUNT] = {6.0f, 1.0f, 0.4f, 0.5f, 0.5f, 0.5f, 0.5f, 2.5f, 3.0f, 0.3f, 0.3f, 60.0f,
                                         0.2f, 0.3f, 1.0f, 1.0f, 0.3f, 0.5f, 1.0f, 10.0f, 0.5f, 0.5f, 0.3f};
  lo = i < PARAM_COUNT ? kLo[i] : 0;
  hi = i < PARAM_COUNT ? kHi[i] : 0;
}

void sanitize(Params& p) {
  for (size_t i = 0; i < PARAM_COUNT; ++i) {
    float lo, hi;
    paramRange(i, lo, hi);
    float& v = param(p, i);
    if (!(v == v)) v = param(idealParams(), i);  // NaN
    v = clampf(v, lo, hi);
  }
}

Params idealParams() {
  Params p{};
  p.ratio = 3.0f;
  p.charSpace = 1.0f;
  p.wordSpace = 1.0f;
  p.driftTau = 4.0f;
  p.hesitateDits = 2.0f;
  return p;
}

Params preset(uint8_t style) {
  Params p = idealParams();
  switch (style) {
    case OLD_TIMER:  // bug key: machine-steady dits, long hand-made dahs, heavy weighting
      p.ratio = 4.4f;          // ~4.0 heard with the weighting below
      p.ratioSpread = 0.12f;
      p.weight = 0.15f;
      p.sigmaDit = 0.02f;
      p.sigmaDah = 0.08f;
      p.sigmaGap = 0.04f;
      p.sigmaSpace = 0.04f;
      p.charSpace = 1.30f;
      p.wordSpace = 1.35f;
      p.wordTempo = 0.02f;
      p.driftSigma = 0.02f;
      p.driftTau = 8.0f;
      p.common = 0.08f;
      p.rare = 0.05f;
      p.hesitate = 0.05f;
      p.hesitateDits = 2.0f;
      p.errorProb = 0.002f;
      break;
    case SELF_TAUGHT:  // uneven ratios per letter, jumpy tempo, more errors
      p.ratio = 3.1f;
      p.ratioSpread = 0.5f;
      p.sigmaDit = 0.10f;
      p.sigmaDah = 0.10f;
      p.sigmaGap = 0.20f;
      p.sigmaSpace = 0.20f;
      p.charSpace = 1.10f;
      p.wordSpace = 1.20f;
      p.wordTempo = 0.06f;
      p.driftSigma = 0.08f;
      p.driftTau = 2.0f;
      p.fatigue = 0.01f;
      p.fatigueMax = 0.05f;
      p.lastStretch = 0.10f;
      p.lastProb = 0.20f;
      p.common = 0.10f;
      p.rare = 0.15f;
      p.hesitate = 0.5f;
      p.hesitateDits = 3.0f;
      p.splitProb = 0.04f;
      p.runProb = 0.08f;
      p.errorProb = 0.02f;
      break;
    case STRAIGHT_KEY:  // everything jitters, last element stretched, slows down with fatigue
      p.ratio = 3.15f;
      p.ratioSpread = 0.2f;
      p.weight = 0.06f;
      p.sigmaDit = 0.10f;
      p.sigmaDah = 0.12f;
      p.sigmaGap = 0.12f;
      p.sigmaSpace = 0.12f;
      p.charSpace = 1.25f;
      p.wordSpace = 1.20f;
      p.wordTempo = 0.04f;
      p.driftSigma = 0.05f;
      p.driftTau = 4.0f;
      p.fatigue = 0.03f;
      p.fatigueMax = 0.08f;
      p.lastStretch = 0.25f;
      p.lastProb = 0.6f;
      p.common = 0.06f;
      p.rare = 0.08f;
      p.hesitate = 0.15f;
      p.hesitateDits = 2.0f;
      p.splitProb = 0.01f;
      p.runProb = 0.02f;
      p.errorProb = 0.006f;
      break;
    default:
      break;
  }
  return p;
}

Params randomParams(uint32_t seed) {
  Rng r(seed);
  uint8_t style = (uint8_t)(r.next() % 3);
  Params p = preset(style);
  static const float lo[3] = {4.1f, 2.6f, 2.8f};
  static const float hi[3] = {4.9f, 3.6f, 3.5f};
  for (size_t i = 0; i < PARAM_COUNT; ++i) {
    float& v = param(p, i);
    if (&v == &p.ratio) v = lo[style] + (hi[style] - lo[style]) * r.uniform();
    else if (&v == &p.charSpace || &v == &p.wordSpace) v = 1.0f + (v - 1.0f) * (0.6f + 0.8f * r.uniform());
    else v *= 0.75f + 0.5f * r.uniform();
  }
  return p;
}

float Rng::gauss() {
  if (spare_) {
    spare_ = false;
    return spareVal_;
  }
  float u1 = uniform() + 1e-7f;
  float u2 = uniform();
  float m = sqrtf(-2.0f * logf(u1));
  float g1 = m * cosf(6.2831853f * u2);
  float g2 = m * sinf(6.2831853f * u2);
  spareVal_ = clampf(g2, -3.0f, 3.0f);
  spare_ = true;
  return clampf(g1, -3.0f, 3.0f);
}

void Fist::configure(const Config& c) {
  enabled_ = c.enabled;
  a_ = clampf(c.amount / 100.0f, 0.0f, 1.0f);
  p100_ = c.p;
  sanitize(p100_);
  // The fist's fixed per-letter ratios come from the settings themselves.
  Rng lr(fnv1a(&p100_, sizeof(p100_)));
  for (float& o : letterOffset_) o = 2.0f * lr.uniform() - 1.0f;
  recompute();
}

void Fist::setTiming(const morse::Timing& t) {
  t_ = t;
  recompute();
}

void Fist::recompute() {
  const Params ideal = idealParams();
  for (size_t i = 0; i < PARAM_COUNT; ++i)
    param(e_, i) = param(ideal, i) + (param(p100_, i) - param(ideal, i)) * a_;
  e_.driftTau = p100_.driftTau < 0.5f ? 0.5f : p100_.driftTau;
  const float a2 = a_ * a_;
  pSplit_ = clampf(p100_.splitProb, 0, 1) * a2;
  pRun_ = clampf(p100_.runProb, 0, 1) * a2;
  pError_ = clampf(p100_.errorProb, 0, 1) * a2;
  pHesitate_ = clampf(p100_.hesitate, 0, 1) * a2;

  // Expected PARIS length with these parameters vs. ideal: rescale the unit.
  k_ = 1.0f;
  if (a_ <= 0.0f) return;
  const float dit = t_.dit, w = e_.weight * dit;
  float ideal_ms = 0, expect_ms = 0;
  const char* word = "PARIS";
  for (const char* c = word; *c; ++c) {
    const char* pat = morse::pattern(*c);
    float r = e_.ratio + e_.ratioSpread * letterOffset_[(*c - ' ') & 63];
    for (size_t i = 0; pat[i]; ++i) {
      bool last = !pat[i + 1];
      float md = t_.markDit + w;
      float mark = pat[i] == '.' ? md : t_.markDah + w + (r - 3.0f) * md;
      if (last) mark *= 1.0f + e_.lastProb * e_.lastStretch;
      float gap = last ? ((t_.elemGap + t_.charExtra) * e_.charSpace - w) * (1.0f - pRun_ * 0.475f)
                       : (t_.elemGap - w) * (1.0f + pSplit_ * 2.0f);
      expect_ms += mark + gap;
      ideal_ms += (pat[i] == '.' ? t_.markDit : t_.markDah) + t_.elemGap + (last ? t_.charExtra : 0);
    }
  }
  expect_ms += t_.wordExtra * e_.wordSpace;
  ideal_ms += t_.wordExtra;
  if (expect_ms > 0) k_ = ideal_ms / expect_ms;
}

void Fist::beginWord(bool common) {
  common_ = common;
  word_ = clampf(1.0f + e_.wordTempo * rng_.gauss(), 0.85f, 1.15f);
}

float Fist::fatigueFactor() const {
  float fat = sentMs_ * (1.0f / 60000.0f) * e_.fatigue;
  if (fat > e_.fatigueMax) fat = e_.fatigueMax;
  return 1.0f + fat;
}

float Fist::tempo() const { return (1.0f + x_) * word_ * ctx_; }

uint16_t Fist::emit(float profileMs, float sigma, float minMs, float idealMs) {
  const float fat = fatigueFactor();
  float d = profileMs * k_ * gov_ * fat * tempo() * (1.0f + sigma * rng_.gauss());
  if (d < minMs) d = minMs;
  if (d > 3000.0f) d = 3000.0f;
  // Ornstein-Uhlenbeck tempo wander, advanced by the element's duration
  float decay = expf(-d / (1000.0f * e_.driftTau));
  x_ = clampf(x_ * decay + e_.driftSigma * sqrtf(1.0f - decay * decay) * rng_.gauss(), -0.3f, 0.3f);
  sentMs_ += d;
  // Speed keeper (exponential window of ~30 s ideal time)
  if (a_ > 0.0f) {
    float lambda = expf(-(idealMs > 0 ? idealMs : d) / 30000.0f);
    idealSum_ = idealSum_ * lambda + idealMs;
    naturalSum_ = naturalSum_ * lambda + d / (fat * gov_);
    if (naturalSum_ > 0 && idealSum_ > 0) gov_ = clampf(idealSum_ / naturalSum_, 0.75f, 1.33f);
  }
  return (uint16_t)lroundf(d);
}

size_t Fist::encode(const char* pat, char letter, uint8_t echo, bool endGap, bool rare, bool hesitate,
                    morse::Element* out, size_t max, bool counts) {
  size_t len = strlen(pat);
  if (2 * len + 1 > max) return 0;
  const float dit = t_.dit, w = e_.weight * dit;
  ctx_ = common_ ? 1.0f - e_.common : (rare ? 1.0f + e_.rare : 1.0f);
  size_t n = 0;
  if (hesitate) out[n++] = {emit(e_.hesitateDits * dit, e_.sigmaSpace, 0, 0), 0, 0};
  float r = e_.ratio + e_.ratioSpread * letterOffset_[(upper(letter) - ' ') & 63];
  for (size_t i = 0; i < len; ++i) {
    bool last = i + 1 == len;
    float md = t_.markDit + w;
    float mark = pat[i] == '.' ? md : t_.markDah + w + (r - 3.0f) * md;
    bool stretch = rng_.uniform() < e_.lastProb;
    if (last && stretch) mark *= 1.0f + e_.lastStretch;
    float idealMark = counts ? (pat[i] == '.' ? t_.markDit : t_.markDah) : 0;
    out[n++] = {emit(mark, pat[i] == '.' ? e_.sigmaDit : e_.sigmaDah, 0.4f * dit, idealMark), 1,
                (uint8_t)(i == 0 ? echo : 0)};
    float gap;
    if (!last || !endGap) {
      gap = t_.elemGap - w;
      if (!last && rng_.uniform() < pSplit_) gap *= 2.5f + rng_.uniform();  // letter splits in two
      float idealGap = counts ? (float)t_.elemGap : 0;
      out[n++] = {emit(gap, e_.sigmaGap, 0.3f * dit, idealGap), 0, 0};
    } else {
      gap = (t_.elemGap + t_.charExtra) * e_.charSpace - w;
      if (rng_.uniform() < pRun_) gap *= 0.45f + 0.15f * rng_.uniform();  // letters run together
      out[n++] = {emit(gap, e_.sigmaSpace, 0.3f * dit, counts ? (float)(t_.elemGap + t_.charExtra) : 0), 0, 0};
    }
  }
  ctx_ = 1.0f;
  return n;
}

uint16_t Fist::wordGap(bool counts) {
  return emit(t_.wordExtra * e_.wordSpace, e_.sigmaSpace, 0, counts ? (float)t_.wordExtra : 0);
}

uint16_t Fist::prosignEnd() { return emit(t_.charExtra * e_.charSpace, e_.sigmaSpace, 0, t_.charExtra); }

bool mutatePattern(const char* in, char* out, uint32_t r) {
  size_t n = strlen(in);
  if (n == 0 || n > 7) return false;
  // options: 0..n-1 = drop the dit at index j; n..2n = insert a dit at index j-n
  int opts[16];
  int k = 0;
  for (size_t j = 0; j < n; ++j)
    if (in[j] == '.' && n >= 2) opts[k++] = (int)j;
  if (n < 6)
    for (size_t j = 0; j <= n; ++j)
      if ((j > 0 && in[j - 1] == '.') || (j < n && in[j] == '.') || j == n) opts[k++] = (int)(n + j);
  if (k == 0) return false;
  int o = opts[r % (uint32_t)k];
  size_t m = 0;
  if (o < (int)n) {
    for (size_t j = 0; j < n; ++j)
      if ((int)j != o) out[m++] = in[j];
  } else {
    size_t at = (size_t)o - n;
    for (size_t j = 0; j <= n; ++j) {
      if (j == at) out[m++] = '.';
      if (j < n) out[m++] = in[j];
    }
  }
  out[m] = 0;
  return true;
}

bool isCommonWord(const char* w, size_t n) {
  static const char* const kCommon[] = {"CQ", "DE", "TU", "73", "5NN", "599", "TNX", "TKS", "FB", "ES",
                                        "UR", "RST", "K", "KN", "BK", "R", "GM", "GA", "GE", "OM",
                                        "QSL", "QRZ", "QTH", "HW?", "NAME", "RIG", "ANT", "WX", "88", "TEST"};
  if (n == 0 || n > 5) return false;
  for (const char* c : kCommon) {
    if (strlen(c) != n) continue;
    size_t i = 0;
    while (i < n && upper(w[i]) == c[i]) ++i;
    if (i == n) return true;
  }
  return false;
}

}  // namespace human
