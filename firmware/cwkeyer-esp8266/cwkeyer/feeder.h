// CW keyer – tekstijono, joka muunnetaan elementeiksi merkki kerrallaan.
// Muunnos tehdään vasta juuri ennen lähetystä, joten nopeuden muutos
// vaikuttaa heti jonossa oleviin merkkeihin (FR-TX-04).
// Puhdas C++ (testattavissa PC:llä).
#pragma once
#include "morse.h"

template <size_t N>
class Feeder {
 public:
  // Lisää tekstiä jonoon. Palauttaa hyväksyttyjen merkkien määrän.
  size_t push(const char* s, size_t len) {
    size_t k = 0;
    for (; k < len; ++k) {
      if (count_ == N) break;
      buf_[(head_ + count_) % N] = s[k];
      ++count_;
    }
    return k;
  }

  size_t pending() const { return count_; }

  void clear() {
    count_ = 0;
    head_ = 0;
    inProsign_ = false;
  }

  // Tuottaa seuraavan merkin elementit. Palauttaa:
  //  -1 jono tyhjä, 0 merkki ohitettiin (ei tuettu), >0 elementtien määrä.
  // out-puskurissa on oltava tilaa vähintään 16 elementille.
  int next(const morse::Timing& t, morse::Element* out, size_t max) {
    if (count_ == 0) return -1;
    char c = buf_[head_];
    head_ = (head_ + 1) % N;
    --count_;

    if (c == '<') {  // prosign alkaa: kirjaimet ilman merkkiväliä, esim. <SK>
      inProsign_ = true;
      out[0] = {0, 0, '<'};
      return 1;
    }
    if (c == '>') {
      if (!inProsign_) return 0;
      inProsign_ = false;
      out[0] = {t.charExtra, 0, '>'};
      return 1;
    }
    if (morse::isWordSpace(c)) {
      if (inProsign_) return 0;
      out[0] = {t.wordExtra, 0, ' '};
      return 1;
    }
    size_t n = morse::encodeChar(c, t, out, max - 1);
    if (n == 0) return 0;
    if (!inProsign_) out[n++] = {t.charExtra, 0, 0};
    return (int)n;
  }

 private:
  char buf_[N];
  size_t head_ = 0;
  size_t count_ = 0;
  bool inProsign_ = false;
};
