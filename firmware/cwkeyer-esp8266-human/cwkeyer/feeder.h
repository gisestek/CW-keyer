// CW keyer – tekstijono, joka muunnetaan elementeiksi merkki kerrallaan.
// Muunnos tehdään vasta juuri ennen lähetystä, joten nopeuden muutos
// vaikuttaa heti jonossa oleviin merkkeihin (FR-TX-04).
// Puhdas C++ (testattavissa PC:llä).
//
// Human emulation: when a Fist is attached and enabled, characters are timed
// by the fist (human.h). At the start of each word the feeder looks ahead at
// the whole word: it decides the word's context (common sequence, or the call
// after DE) and whether the operator makes a mistake in it. A mistake is sent
// as the word up to the bad character (and maybe one more), then 8 dits, then
// the whole word again. Only the final, correct word is echoed.
#pragma once
#include <cstring>

#include "human.h"
#include "morse.h"

template <size_t N>
class Feeder {
 public:
  void setHuman(human::Fist* f) { fist_ = f; }

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
    resetWord();
    prevDe_ = false;
  }

  // Tuottaa seuraavan merkin elementit. Palauttaa:
  //  -1 jono tyhjä, 0 merkki ohitettiin (ei tuettu), >0 elementtien määrä.
  // out-puskurissa on oltava tilaa vähintään 16 elementille.
  int next(const morse::Timing& t, morse::Element* out, size_t max) {
    if (fist_ && fist_->enabled()) return nextHuman(out, max);
    if (wordActive_) resetWord();
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
  static constexpr size_t WORD_MAX = 24;

  char peek(size_t i) const { return buf_[(head_ + i) % N]; }

  void resetWord() {
    wordActive_ = false;
    attempt_ = false;
    correction_ = false;
    hesitated_ = false;
    wordLen_ = 0;
  }

  // First character of a new word: look ahead, set the context, maybe plan a mistake.
  void startWord() {
    resetWord();
    wordActive_ = true;
    bool complete = false;
    bool prosign = false;
    while (wordLen_ < count_ && wordLen_ < WORD_MAX) {
      char c = peek(wordLen_);
      if (morse::isWordSpace(c)) {
        complete = true;
        break;
      }
      if (c == '<' || c == '>') prosign = true;
      word_[wordLen_++] = c;
    }
    if (wordLen_ == count_ && wordLen_ < WORD_MAX) complete = true;  // last word of the queue
    word_[wordLen_] = 0;
    bool isDe = wordLen_ == 2 && (word_[0] == 'D' || word_[0] == 'd') && (word_[1] == 'E' || word_[1] == 'e');
    bool common = (complete && !prosign && human::isCommonWord(word_, wordLen_)) || (prevDe_ && complete);
    prevDe_ = isDe;
    common_ = common;
    fist_->beginWord(common);
    if (!complete || prosign) return;
    for (size_t i = 0; i < wordLen_; ++i) {
      const char* p = morse::pattern(word_[i]);
      if (p && fist_->rollError() && human::mutatePattern(p, wrong_, fist_->rand())) {
        errIdx_ = i;
        attemptStop_ = i + 1 + (fist_->rand() % 2);  // noticed now or one character later
        if (attemptStop_ > wordLen_) attemptStop_ = wordLen_;
        attemptPos_ = 0;
        attempt_ = true;
        correction_ = true;
        break;
      }
    }
  }

  int emitChar(char c, const char* pat, uint8_t echo, bool endGap, morse::Element* out, size_t max,
               bool counts = true) {
    bool rare = human::isRareChar(c) && !common_;
    bool hes = false;
    if (rare && !hesitated_) {
      hesitated_ = true;
      hes = fist_->rollHesitate();
    }
    return (int)fist_->encode(pat, c, echo, endGap, rare, hes, out, max, counts);
  }

  int nextHuman(morse::Element* out, size_t max) {
    if (attempt_) {  // the mistaken try, not echoed
      if (attemptPos_ < attemptStop_) {
        size_t i = attemptPos_++;
        const char* p = i == errIdx_ ? wrong_ : morse::pattern(word_[i]);
        if (!p) return 0;
        return emitChar(word_[i], p, 0, true, out, max, false);
      }
      attempt_ = false;
    }
    if (correction_) {  // error sign: 8 dits, then a word space before the word is resent
      correction_ = false;
      int n = (int)fist_->encode("........", 'E', 0, true, false, false, out, max, false);
      if (n > 0 && n < (int)max) out[n++] = {fist_->wordGap(false), 0, 0};
      hesitated_ = false;
      return n;
    }
    if (count_ == 0) return -1;
    char c = peek(0);
    if (morse::isWordSpace(c)) {
      head_ = (head_ + 1) % N;
      --count_;
      if (inProsign_) return 0;
      wordActive_ = false;
      out[0] = {fist_->wordGap(), 0, ' '};
      return 1;
    }
    if (!wordActive_) {
      startWord();
      if (attempt_) return nextHuman(out, max);
    }
    head_ = (head_ + 1) % N;
    --count_;
    if (c == '<') {
      inProsign_ = true;
      out[0] = {0, 0, '<'};
      return 1;
    }
    if (c == '>') {
      if (!inProsign_) return 0;
      inProsign_ = false;
      out[0] = {fist_->prosignEnd(), 0, '>'};
      return 1;
    }
    const char* p = morse::pattern(c);
    if (!p) return 0;
    uint8_t echo = (uint8_t)((c >= 'a' && c <= 'z') ? c - 'a' + 'A' : c);
    return emitChar(c, p, echo, !inProsign_, out, max);
  }

  char buf_[N];
  size_t head_ = 0;
  size_t count_ = 0;
  bool inProsign_ = false;

  human::Fist* fist_ = nullptr;
  bool wordActive_ = false;
  bool prevDe_ = false;
  bool common_ = false;
  bool hesitated_ = false;
  bool attempt_ = false;
  bool correction_ = false;
  char word_[WORD_MAX + 1] = {};
  size_t wordLen_ = 0;
  size_t errIdx_ = 0;
  size_t attemptPos_ = 0;
  size_t attemptStop_ = 0;
  char wrong_[10] = {};
};
