// CW keyer – morsekoodaus ja ajoitus.
// Puhdas C++ ilman Arduino-riippuvuuksia, jotta sen voi testata PC:llä (test/).
#pragma once
#include <cstdint>
#include <cstddef>

namespace morse {

// Yksi avainnuselementti: kesto ms, avain alhaalla (1) / ylhäällä (0),
// echo = merkki, joka kaiutetaan elementin alkaessa (0 = ei kaikua).
struct Element {
  uint16_t ms;
  uint8_t key;
  uint8_t echo;
};

struct Timing {
  uint16_t dit;       // perusyksikkö
  uint16_t markDit;   // pisteen avain alhaalla (painotuksen kanssa)
  uint16_t markDah;   // viivan avain alhaalla
  uint16_t elemGap;   // tauko elementtien välissä
  uint16_t charExtra; // lisätauko merkin perään (elemGap + charExtra = 3 yksikköä)
  uint16_t wordExtra; // lisätauko sanavälille (charGap + wordExtra = 7 yksikköä)
};

// PARIS-ajoitus: dit = 1200 / WPM ms. Painotus 50 = normaali; muu arvo
// siirtää aikaa avaimen alas- ja ylhäälläolon välillä (WinKeyer-tyyli).
inline Timing makeTiming(unsigned wpm, unsigned weight) {
  if (wpm < 5) wpm = 5;
  if (wpm > 99) wpm = 99;
  if (weight < 25) weight = 25;
  if (weight > 75) weight = 75;
  Timing t;
  t.dit = (uint16_t)(1200u / wpm);
  int adj = ((int)t.dit * ((int)weight - 50)) / 50;
  t.markDit = (uint16_t)(t.dit + adj);
  t.markDah = (uint16_t)(3 * t.dit + adj);
  t.elemGap = (uint16_t)(t.dit - adj);
  t.charExtra = (uint16_t)(2 * t.dit);
  t.wordExtra = (uint16_t)(4 * t.dit);
  return t;
}

// Palauttaa merkin kuvion ("." ja "-") tai nullptr, jos merkkiä ei tueta.
inline const char* pattern(char c) {
  if (c >= 'a' && c <= 'z') c = (char)(c - 'a' + 'A');
  static const char* const letters[26] = {
    ".-", "-...", "-.-.", "-..", ".", "..-.", "--.", "....", "..", ".---",
    "-.-", ".-..", "--", "-.", "---", ".--.", "--.-", ".-.", "...", "-",
    "..-", "...-", ".--", "-..-", "-.--", "--.."};
  static const char* const digits[10] = {
    "-----", ".----", "..---", "...--", "....-", ".....", "-....", "--...",
    "---..", "----."};
  if (c >= 'A' && c <= 'Z') return letters[c - 'A'];
  if (c >= '0' && c <= '9') return digits[c - '0'];
  switch (c) {
    case '.': return ".-.-.-";
    case ',': return "--..--";
    case '?': return "..--..";
    case '/': return "-..-.";
    case '=': return "-...-";   // BT
    case '+': return ".-.-.";   // AR
    case '-': return "-....-";
    case '(': return "-.--.";   // KN
    case ')': return "-.--.-";
    case '"': return ".-..-.";
    case '\'': return ".----.";
    case ':': return "---...";
    case ';': return "-.-.-.";
    case '@': return ".--.-.";
    case '!': return "-.-.--";
    default: return nullptr;
  }
}

inline bool isWordSpace(char c) { return c == ' ' || c == '\n' || c == '\r' || c == '\t'; }

// Koodaa yhden merkin elementeiksi. Viimeisen elementin jälkeen tulee
// elemGap; kutsuja lisää charExtra-tauon (paitsi prosignin sisällä).
// Palauttaa kirjoitettujen elementtien määrän, 0 jos merkkiä ei tueta
// tai tila ei riitä.
inline size_t encodeChar(char c, const Timing& t, Element* out, size_t max) {
  const char* p = pattern(c);
  if (!p) return 0;
  size_t n = 0;
  for (size_t i = 0; p[i]; ++i) n += 2;
  if (n > max) return 0;
  uint8_t echo = (uint8_t)((c >= 'a' && c <= 'z') ? c - 'a' + 'A' : c);
  size_t k = 0;
  for (size_t i = 0; p[i]; ++i) {
    out[k++] = {p[i] == '.' ? t.markDit : t.markDah, 1, (uint8_t)(i == 0 ? echo : 0)};
    out[k++] = {t.elemGap, 0, 0};
  }
  return k;
}

// Merkin kaikkien elementtien yhteiskesto (testejä varten).
inline unsigned totalMs(const Element* e, size_t n) {
  unsigned s = 0;
  for (size_t i = 0; i < n; ++i) s += e[i].ms;
  return s;
}

}  // namespace morse
