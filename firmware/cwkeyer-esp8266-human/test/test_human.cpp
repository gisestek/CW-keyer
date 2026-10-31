// PC tests for the human emulation timing model (human.h) and the feeder.
// g++ -std=c++17 -I../cwkeyer test_human.cpp ../cwkeyer/human.cpp -o test_human && ./test_human
#include <cmath>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

#include "feeder.h"
#include "human.h"
#include "morse.h"

using Edges = std::vector<std::pair<unsigned, int>>;  // (ms, key) with equal neighbours merged

struct Render {
  std::vector<morse::Element> elems;
  Edges edges;
  std::string echo;
  unsigned totalMs = 0;
};

static const char* QSO =
    "CQ CQ CQ DE OH2XYZ OH2XYZ K "
    "DL1ABC DE OH2XYZ GM OM TNX FER CALL UR RST 579 5NN NAME JUKKA QTH HELSINKI HW? DL1ABC DE OH2XYZ K "
    "R R TNX FER QSO DR HANS RIG IS 100W ANT DIPOLE WX CLOUDY 12C. 73 ES CUL DL1ABC DE OH2XYZ <SK> ";

static human::Config cfg(uint8_t style, uint8_t amount, bool enabled = true) {
  human::Config c;
  c.enabled = enabled;
  c.style = style;
  c.amount = amount;
  c.p = style == human::RANDOM ? human::randomParams(1234) : human::preset(style);
  return c;
}

// Feed the text through Feeder (+ optional fist) like keyer::service does.
static Render render(const human::Config* c, unsigned wpm, unsigned weight, const char* text, uint32_t seed = 1) {
  Render r;
  morse::Timing t = morse::makeTiming(wpm, weight);
  static human::Fist fist;
  fist = human::Fist();
  static Feeder<4096> f;
  f.clear();
  f.setHuman(nullptr);
  if (c) {
    fist.configure(*c);
    fist.setTiming(t);
    fist.seed(seed);
    f.setHuman(&fist);
  }
  f.push(text, strlen(text));
  morse::Element tmp[24];
  int n;
  while ((n = f.next(t, tmp, 24)) >= 0)
    for (int i = 0; i < n; ++i) r.elems.push_back(tmp[i]);
  for (auto& e : r.elems) {
    if (e.echo) r.echo += (char)e.echo;
    r.totalMs += e.ms;
    if (e.ms == 0) continue;
    if (!r.edges.empty() && r.edges.back().second == e.key) r.edges.back().first += e.ms;
    else r.edges.push_back({e.ms, e.key});
  }
  return r;
}

static bool sameElems(const Render& a, const Render& b) {
  if (a.elems.size() != b.elems.size()) return false;
  for (size_t i = 0; i < a.elems.size(); ++i)
    if (a.elems[i].ms != b.elems[i].ms || a.elems[i].key != b.elems[i].key || a.elems[i].echo != b.elems[i].echo)
      return false;
  return true;
}

static int countErrorSigns(const Edges& e, unsigned wpm) {
  // 8 consecutive short marks separated by short gaps
  unsigned dit = 1200 / wpm;
  int count = 0, run = 0;
  for (size_t i = 0; i < e.size(); ++i) {
    if (e[i].second) {
      if (e[i].first < 2 * dit) ++run;
      else run = 0;
      if (run == 8) ++count;
    } else if (e[i].first > 2 * dit) {
      run = 0;
    }
  }
  return count;
}

int main() {
  int fails = 0;
  auto check = [&](bool ok, const char* what) {
    printf("%s  %s\n", ok ? "OK  " : "FAIL", what);
    if (!ok) ++fails;
  };
  const uint8_t styles[] = {human::OLD_TIMER, human::SELF_TAUGHT, human::STRAIGHT_KEY, human::RANDOM};
  const char* sname[] = {"old timer", "self-taught", "straight key", "random"};

  // --- emulation off = unchanged output ---
  {
    bool ok = true;
    for (unsigned wpm : {12u, 20u, 32u})
      for (unsigned wt : {40u, 50u, 65u})
        for (uint8_t s : styles) {
          human::Config c = cfg(s, 100, false);
          ok &= sameElems(render(nullptr, wpm, wt, QSO), render(&c, wpm, wt, QSO));
        }
    check(ok, "emulation off: elements identical to the plain keyer (all styles, WPM, weights)");
  }

  // --- amount 0 = ideal timing ---
  {
    bool ok = true;
    for (unsigned wpm : {12u, 20u, 32u})
      for (unsigned wt : {40u, 50u, 65u})
        for (uint8_t s : styles) {
          human::Config c = cfg(s, 0);
          Render ideal = render(nullptr, wpm, wt, QSO), h = render(&c, wpm, wt, QSO, 77);
          ok &= ideal.edges == h.edges && ideal.echo == h.echo;
        }
    check(ok, "amount 0 %: key timing and echo identical to the ideal keyer");
  }

  // --- determinism ---
  for (int i = 0; i < 4; ++i) {
    human::Config c = cfg(styles[i], 100);
    Render a = render(&c, 22, 50, QSO, 42), b = render(&c, 22, 50, QSO, 42), d = render(&c, 22, 50, QSO, 43);
    std::string w = std::string("same settings + same seed = identical timing, other seed differs: ") + sname[i];
    check(sameElems(a, b) && !sameElems(a, d), w.c_str());
  }
  {
    human::Config a = cfg(human::OLD_TIMER, 100), b = cfg(human::STRAIGHT_KEY, 100);
    check(!sameElems(render(&a, 22, 50, QSO, 5), render(&b, 22, 50, QSO, 5)), "different style = different timing");
    human::Params p1 = human::randomParams(99), p2 = human::randomParams(99), p3 = human::randomParams(100);
    check(!memcmp(&p1, &p2, sizeof p1) && memcmp(&p1, &p3, sizeof p1), "random style: same seed = same parameters");
  }

  // --- average speed stays within 10 % of the set WPM ---
  for (int i = 0; i < 4; ++i)
    for (uint8_t amt : {50, 100}) {
      double worst = 0;
      for (unsigned wpm : {12u, 18u, 25u, 32u, 40u})
        for (uint32_t seed = 1; seed <= 8; ++seed) {
          human::Config c = cfg(styles[i], amt);
          Render ideal = render(nullptr, wpm, 50, QSO), h = render(&c, wpm, 50, QSO, seed);
          double eff = (double)ideal.totalMs / h.totalMs;  // effective WPM / set WPM
          if (fabs(eff - 1) > worst) worst = fabs(eff - 1);
        }
      char w[120];
      snprintf(w, sizeof w, "average WPM within 10 %%: %s %u %% (worst %.1f %%)", sname[i], amt, worst * 100);
      check(worst < 0.10, w);
    }

  // --- echo is always the text, also with mistakes and corrections ---
  {
    human::Config c = cfg(human::SELF_TAUGHT, 100);
    c.p.errorProb = 0.15f;
    bool ok = true;
    int signs = 0;
    for (uint32_t seed = 1; seed <= 10; ++seed) {
      Render h = render(&c, 20, 50, QSO, seed);
      ok &= h.echo == render(nullptr, 20, 50, QSO).echo;
      signs += countErrorSigns(h.edges, 20);
    }
    check(ok, "mistakes: echo equals the text (only the corrected word is echoed)");
    check(signs > 10, "mistakes are corrected with 8 dits");
    // error probability scales with amount²
    int s30 = 0, s100 = 0;
    for (uint32_t seed = 1; seed <= 30; ++seed) {
      human::Config c30 = c;
      c30.amount = 30;
      s30 += countErrorSigns(render(&c30, 20, 50, QSO, seed).edges, 20);
      s100 += countErrorSigns(render(&c, 20, 50, QSO, seed).edges, 20);
    }
    char w[100];
    snprintf(w, sizeof w, "error rate scales with amount²: 30 %% = %d, 100 %% = %d (expect ~9 %%)", s30, s100);
    check(s100 > 50 && s30 < s100 * 0.2, w);
    human::Config oldt = cfg(human::OLD_TIMER, 100);
    int so = 0;
    for (uint32_t seed = 1; seed <= 10; ++seed) so += countErrorSigns(render(&oldt, 20, 50, QSO, seed).edges, 20);
    check(so <= 3, "old timer: errors very rare");
  }

  // --- mutatePattern ---
  {
    char out[10];
    bool ok = true;
    for (uint32_t r = 0; r < 20; ++r) {
      human::mutatePattern("....", out, r);
      ok &= !strcmp(out, "...") || !strcmp(out, ".....");
      human::mutatePattern("-", out, r);
      ok &= strlen(out) == 2 && strchr(out, '.');
    }
    check(ok, "dropped/extra dit: H -> S or 5, T -> A or N");
  }

  // --- style character, measured from single characters ---
  auto stats = [](uint8_t style, char letter, const char* pat, std::vector<double>& dits, std::vector<double>& dahs,
                   std::vector<double>* lastDit = nullptr) {
    human::Fist f;
    human::Config c = cfg(style, 100);
    f.configure(c);
    f.setTiming(morse::makeTiming(20, 50));
    f.seed(3);
    morse::Element e[24];
    for (int k = 0; k < 400; ++k) {
      f.beginWord(false);
      size_t n = f.encode(pat, letter, 0, true, false, false, e, 24);
      for (size_t i = 0; i < n; ++i) {
        if (!e[i].key) continue;
        bool isDit = pat[i / 2] == '.';
        bool last = i + 2 >= n;
        if (lastDit && last && isDit) lastDit->push_back(e[i].ms);
        else (isDit ? dits : dahs).push_back(e[i].ms);
      }
    }
  };
  auto mean = [](const std::vector<double>& v) { double s = 0; for (double x : v) s += x; return v.empty() ? 0 : s / v.size(); };
  auto cv = [&](const std::vector<double>& v) {
    double m = mean(v), s = 0;
    for (double x : v) s += (x - m) * (x - m);
    return sqrt(s / v.size()) / m;
  };
  {
    std::vector<double> d, h;
    stats(human::OLD_TIMER, 'C', "-.-.", d, h);
    char w[120];
    snprintf(w, sizeof w, "old timer: dah/dit %.2f (3.8-4.5), dit jitter %.1f %%, dah jitter %.1f %%", mean(h) / mean(d),
             cv(d) * 100, cv(h) * 100);
    check(mean(h) / mean(d) > 3.8 && mean(h) / mean(d) < 4.5 && cv(d) < cv(h), w);
  }
  {
    double lo = 9, hi = 0;
    for (char c : std::string("ABCDGKNQUVWXY")) {
      std::vector<double> d, h;
      stats(human::SELF_TAUGHT, c, morse::pattern(c), d, h);
      double r = mean(h) / mean(d);
      lo = r < lo ? r : lo;
      hi = r > hi ? r : hi;
    }
    char w[120];
    snprintf(w, sizeof w, "self-taught: dah/dit ratio differs per letter (%.2f-%.2f)", lo, hi);
    check(hi - lo > 0.4 && lo > 2.3 && hi < 3.9, w);
  }
  {
    std::vector<double> d, h, last;
    stats(human::STRAIGHT_KEY, 'S', "...", d, h, &last);
    char w[120];
    snprintf(w, sizeof w, "straight key: last element stretched (%.0f vs %.0f ms), dit jitter %.1f %%", mean(last),
             mean(d), cv(d) * 100);
    check(mean(last) > mean(d) * 1.08 && cv(d) > 0.07, w);
  }

  // --- straight key slows down over a long transmission (fatigue) ---
  {
    human::Config c = cfg(human::STRAIGHT_KEY, 100);
    std::string longText;
    for (int i = 0; i < 6; ++i) longText += QSO;
    Render h = render(&c, 25, 50, longText.c_str(), 9);
    // compare the first and last quarter of the marks
    std::vector<unsigned> marks;
    for (auto& e : h.edges) if (e.second) marks.push_back(e.first);
    size_t q = marks.size() / 4;
    double a = 0, b = 0;
    for (size_t i = 0; i < q; ++i) { a += marks[i]; b += marks[marks.size() - 1 - i]; }
    char w[100];
    snprintf(w, sizeof w, "straight key: fatigue, last quarter %.0f %% slower", (b / a - 1) * 100);
    check(b > a * 1.04, w);
  }

  printf("\n%s (%d failed)\n", fails ? "FAILED" : "ALL OK", fails);
  return fails ? 1 : 0;
}
