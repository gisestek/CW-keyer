# cwkeyer-esp8266-human – WiFi keyer with human emulation

Version 0.2.0 · 2026-10-25 · AGPL-3.0-or-later

An alternative firmware for the same Wemos D1 mini keyer as [`../cwkeyer-esp8266`](../cwkeyer-esp8266/README.md). Same wiring, same WebSocket protocol ([PROTOCOL.md](PROTOCOL.md)), same safety limits. CW Station needs no changes.

The difference: the keyer can send like a real operator instead of a perfect machine. You set how human it sounds on a web page served by the keyer itself. Speed and weight still come from CW Station; the human effect is applied on top.

## Settings page

Open **http://cwkeyer.local/** (or the keyer's IP address, shown in the serial log) once the keyer is on your home WiFi. There is no password; the page is meant for your own network.

| Setting | Meaning |
| --- | --- |
| Human emulation | On/off. Off (the default) sends exactly like `cwkeyer-esp8266`. |
| Style | Old timer (bug key), Self-taught, Straight key, Random, Custom |
| Amount | 0–100 %. 0 % is perfect timing; every parameter moves linearly towards the style's value at 100 %. Mistakes, split letters and hesitations grow with amount², so low settings stay clean. |
| Fine-tune the fist | Every parameter of the style at 100 %. Editing any value switches the style to Custom. |

The settings are the operator's "handwriting": the same settings always give the same fist, including the per-letter dah lengths. **Random** rolls a style and randomized values once; they are saved and stay until you press *Roll a new random fist*.

Changes apply to text queued after you press Save. They are written to flash when the keyer is not sending, because writing flash pauses interrupts for a moment.

### Styles at 100 %

| | Old timer (bug key) | Self-taught | Straight key |
| --- | --- | --- | --- |
| Dah/dit ratio | ~4.2 heard, nearly the same for all letters | 2.6–3.6, different per letter | ~3.2 |
| Jitter | dits ~2 %, dahs ~8 % | gaps ~20 % | dits ~10 %, dahs ~12 %, gaps ~12 % |
| Weighting | heavy, +15 % | none | slight, +6 % |
| Spacing | long, steady letter and word spaces | sometimes splits a letter, sometimes runs letters together | long letter spaces, last element of a letter often stretched |
| Tempo | smooth slow wander | jumpy, hesitates before numbers | slows down over long overs (fatigue, max 8 %) |
| Mistakes | very rare | frequent: dropped/extra dit (H↔S), corrected with 8 dits and the word sent again | occasional |

All styles send common sequences (CQ, DE, TU, 73, 5NN, the call after DE, …) slightly faster, and numbers and punctuation slightly slower.

## How it works

`cwkeyer/human.cpp` contains the timing model; it has no Arduino dependencies. Each element is

```
dur = ideal × profile(element, letter, position) × context × drift(t) × fatigue(t) × (1 + gauss(0, σ))
```

- **profile**: dah/dit ratio (per-letter offset fixed by the settings), weighting, letter and word space multipliers, stretched last element.
- **context**: common words faster, numbers and punctuation slower, optional hesitation before them.
- **drift**: Ornstein–Uhlenbeck tempo wander with a time constant of a few seconds; per-word tempo change gives a phrase-like rhythm.
- **speed keeper**: like an operator holding a speed, the tempo is nudged over a ~30 s window so the average stays at the WPM set by CW Station (fatigue is left out of this on purpose).
- **mistakes**: at the start of each word the feeder (`feeder.h`) looks at the whole word and decides whether the operator gets a letter wrong. If so it sends the word up to that letter (sometimes one more), 8 dits, a word space, and the whole word again. Only the corrected word is echoed, so CW Station's TX log stays clean.

The 1 ms timer interrupt and the safety limits (`keyer.cpp`) are unchanged: the model only decides how long each element in the buffer is.

## Building and uploading

Exactly as for `cwkeyer-esp8266` (PlatformIO, same libraries):

```
cd firmware/cwkeyer-esp8266-human
pio run -t upload                  # USB
pio run -e d1_mini_ota -t upload   # WiFi (OTA)
pio device monitor                 # serial log: [human] ..., [web] http://cwkeyer.local/
```

Settings are stored in the EEPROM area of flash, so switching back and forth between the two firmwares is safe. The original firmware ignores them.

## Tests (PC, no hardware)

```
cd test
g++ -std=c++17 -Ishim -I../cwkeyer test_keyer.cpp ../cwkeyer/keyer.cpp ../cwkeyer/human.cpp -o test_keyer && ./test_keyer
g++ -std=c++17 -I../cwkeyer test_human.cpp ../cwkeyer/human.cpp -o test_human && ./test_human
```

- `test_keyer`: all original keyer tests unchanged (emulation is off by default), plus a human-emulation run through the interrupt: echo, mistakes, STOP, heartbeat, and exact PARIS timing after switching it off again.
- `test_human`:
  - emulation off gives elements identical to the plain keyer
  - amount 0 % gives key timing identical to ideal, for all styles, speeds and weights
  - the same settings and seed give identical timing
  - the average WPM stays within 10 % for every style at 50 % and 100 % (measured: at most about 6 %)
  - the echo is always the text
  - the error rate scales with amount²
  - each style's character is checked: old timer ratio, per-letter ratios, last-element stretch and fatigue

## Trying the styles

1. Upload, then open http://cwkeyer.local/, turn **Human emulation** on and press Save.
2. In CW Station send the F1 CQ macro, or something like `CQ CQ DE <call> 599 5NN TU 73`, with the transmitter on a dummy load or the sidetone only.
3. **Old timer** at 100 %: long, swinging dahs against dead-steady dits, roomy letter spacing.
4. **Self-taught** at 100 %: uneven letters, pauses before numbers. With longer texts you will hear 8 dits and a repeated word now and then.
5. **Straight key** at 100 %: everything a bit loose; send a long over (F5) and it slows down towards the end.
6. Drop **Amount** to 20–30 % for a natural but clean fist; mistakes practically disappear there.
7. **Random**: press *Roll a new random fist* until you like it, then Save.
