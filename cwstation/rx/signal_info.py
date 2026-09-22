"""Extra information about the received signal: speed, pitch, station identity.

The DeepCW model gives decoded characters with time spans; the audio gives the
pitch. From those we derive:

* `wpm_from_chars`  – the other station's speed (linear fit of character start
  times against the cumulative number of Morse units). Accurate to about ±0.5 %
  at 18–35 WPM and it still works at −10 dB SNR, even when a few characters
  are decoded wrong.
* `tone_hz`         – the pitch of one character (parabolic interpolation of the
  FFT peak, sub-Hz accuracy). Per character it tells which station sent it.
* `StationTracker`  – groups pitches into stations so the GUI can colour them.

License: AGPL-3.0-or-later.
"""
from __future__ import annotations

import math

import numpy as np

# Morse patterns, only needed for the element count of a character.
_MORSE = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.", "G": "--.", "H": "....",
    "I": "..", "J": ".---", "K": "-.-", "L": ".-..", "M": "--", "N": "-.", "O": "---", "P": ".--.",
    "Q": "--.-", "R": ".-.", "S": "...", "T": "-", "U": "..-", "V": "...-", "W": ".--", "X": "-..-",
    "Y": "-.--", "Z": "--..", "0": "-----", "1": ".----", "2": "..---", "3": "...--", "4": "....-",
    "5": ".....", "6": "-....", "7": "--...", "8": "---..", "9": "----.", ".": ".-.-.-", ",": "--..--",
    "?": "..--..", "/": "-..-.", "=": "-...-", "+": ".-.-.", "-": "-....-", "(": "-.--.", ")": "-.--.-",
    ":": "---...", "'": ".----.", '"': ".-..-.", "@": ".--.-.",
}

MIN_WPM, MAX_WPM = 5.0, 60.0
TONE_MIN_HZ, TONE_MAX_HZ = 350.0, 1250.0
STATION_TOL_HZ = 30.0       # pitches closer than this are the same station
STATION_TTL_S = 600.0       # a station not heard for this long is forgotten
MAX_STATIONS = 4


def char_units(ch: str) -> int | None:
    """Length of a character in dit units, spacing excluded (e.g. K = -.- = 9)."""
    code = _MORSE.get(ch.upper())
    if not code:
        return None
    return sum(3 if s == "-" else 1 for s in code) + (len(code) - 1)


def wpm_from_chars(chars, min_chars: int = 5) -> float | None:
    """PARIS speed from `[(char, t_start, t_end), ...]` (times in seconds).

    Fits start_time ≈ dit × cumulative_units + a × character_length + b. The
    model marks a character at a point that depends a little on how long the
    character is, which the second term absorbs; what is left is the dit length.
    Measured against synthetic CW the error stays under 0.5 % from 13 to 35 WPM
    and down to −10 dB SNR, also for segments of only seven characters.
    """
    xs, us, ys, cum, in_space = [], [], [], 0, False
    for item in chars:
        ch, t0 = item[0], float(item[1])
        if ch == " ":
            if not in_space:
                cum += 4      # word space is 7 units, 3 of which were already added
                in_space = True
            continue
        in_space = False
        u = char_units(ch)
        if u is None:
            continue
        xs.append(cum)
        us.append(u)
        ys.append(t0)
        cum += u + 3          # character plus the space after it
    if len(xs) < min_chars or xs[-1] == xs[0] or len(set(us)) < 2:
        return None
    x = np.asarray(xs, dtype=float)
    y = np.asarray(ys, dtype=float)
    a = np.vstack([x, np.asarray(us, dtype=float), np.ones(len(x))]).T
    beta, *_ = np.linalg.lstsq(a, y, rcond=None)
    slope = float(beta[0])
    if slope <= 0:
        return None
    # the timing must really be linear: otherwise this was not one steady transmission
    resid = y - a @ beta
    var = float(((y - y.mean()) ** 2).sum())
    if not var or 1.0 - float((resid ** 2).sum()) / var < 0.99:
        return None
    wpm = 1.2 / slope
    return round(wpm, 1) if MIN_WPM <= wpm <= MAX_WPM else None


def tone_hz(audio: np.ndarray, fs: int, start: int, end: int, margin: int = 0,
            min_len: int = 320) -> float | None:
    """Pitch of `audio[start:end]` in Hz, or None if the segment has no clear tone.

    Parabolic interpolation of the log-power FFT peak inside the CW band. The
    window is widened symmetrically to `min_len` samples (100 ms at 3200 Hz) so
    that a single dit still gives a usable frequency resolution.
    """
    a = max(0, int(start) - margin)
    b = min(len(audio), int(end) + margin)
    if b - a < min_len:
        grow = (min_len - (b - a) + 1) // 2
        a, b = max(0, a - grow), min(len(audio), b + grow)
    seg = audio[a:b]
    if len(seg) < 128:
        return None
    n = 1 << int(math.ceil(math.log2(len(seg))))
    spec = np.abs(np.fft.rfft(seg.astype(np.float32) * np.hanning(len(seg)).astype(np.float32), n=n)) ** 2
    freqs = np.fft.rfftfreq(n, 1.0 / fs)
    band = (freqs >= TONE_MIN_HZ) & (freqs <= TONE_MAX_HZ)
    if not band.any():
        return None
    masked = np.where(band, spec, 0.0)
    k = int(masked.argmax())
    if k <= 0 or k >= len(spec) - 1 or masked[k] <= 0:
        return None
    # The peak must stand out from the band's typical level, or it is just noise.
    # In pure noise the largest of n bins is about log2(n) times the median, so
    # the limit grows with the number of bins in the band.
    n_bins = int(band.sum())
    limit = 3.0 * math.log2(max(4, n_bins))
    if masked[k] < limit * float(np.median(spec[band])):
        return None
    lo, mid, hi = (math.log(spec[k - 1] + 1e-30), math.log(spec[k] + 1e-30), math.log(spec[k + 1] + 1e-30))
    denom = lo - 2 * mid + hi
    delta = 0.5 * (lo - hi) / denom if denom else 0.0
    f = (k + max(-0.5, min(0.5, delta))) * fs / n
    return round(float(f), 1) if TONE_MIN_HZ <= f <= TONE_MAX_HZ else None


SNR_BIAS_DB = 1.8        # measured bias of the estimator against a known signal
SNR_REF_BW_HZ = 500.0    # reported in the bandwidth of a normal CW filter


def snr_db(audio: np.ndarray, fs: int, tone: float, start: int = 0, end: int | None = None,
           win: int = 256, hop: int = 64) -> float | None:
    """Signal-to-noise ratio of a transmission in dB, in a 500 Hz bandwidth.

    Key-down power is the 90th percentile of the power around the pitch over
    time (so the ratio of dits to spaces does not matter), and the noise comes
    from the rest of the CW band. Checked against synthetic signals from −6 to
    +30 dB at 13–35 WPM: within about ±2 dB.
    """
    seg = audio[start:end if end is not None else len(audio)]
    if len(seg) < 3 * win or not tone:
        return None
    window = np.hanning(win).astype(np.float32)
    n = 1 + (len(seg) - win) // hop
    idx = np.arange(win)[None, :] + hop * np.arange(n)[:, None]
    power = np.abs(np.fft.rfft(seg[idx] * window, n=512, axis=1)) ** 2
    freqs = np.fft.rfftfreq(512, 1.0 / fs)
    df = fs / 512
    near = np.abs(freqs - tone) <= 45
    far = ((freqs >= 300) & (freqs <= 1400)) & (np.abs(freqs - tone) > 90)
    if not near.any() or not far.any():
        return None
    noise_bin = float(np.median(power[:, far]))     # noise power in one bin
    if noise_bin <= 0:
        return None
    key_down = float(np.percentile(power[:, near].sum(axis=1), 90)) - noise_bin * int(near.sum())
    if key_down <= 0:
        return None
    value = 10 * math.log10(key_down / (noise_bin * SNR_REF_BW_HZ / df)) - SNR_BIAS_DB
    return round(value, 1)


# Signal report suggestion. S runs in 6 dB steps (one S unit), R follows how
# readable the signal is: full copy from about +6 dB in a 500 Hz filter.
def rst_from_snr(snr: float | None) -> str | None:
    if snr is None:
        return None
    s = max(1, min(9, int(snr // 6) + 4))          # 0…6 dB -> S4, 30 dB and up -> S9
    r = 5 if snr >= 6 else 4 if snr >= 0 else 3 if snr >= -6 else 2 if snr >= -12 else 1
    return f"{r}{s}9"


def median_tone(tones) -> float | None:
    vals = [t for t in tones if t]
    if not vals:
        return None
    return round(float(np.median(vals)), 1)


class StationTracker:
    """Gives every pitch a small station index so the GUI can colour stations.

    Index 0 is kept for the station we are working: the first one heard, or
    (once we know our own sidetone pitch) the one closest to it.
    """

    def __init__(self, tol_hz: float = STATION_TOL_HZ, ttl_s: float = STATION_TTL_S,
                 max_stations: int = MAX_STATIONS):
        self.tol, self.ttl, self.max = tol_hz, ttl_s, max_stations
        self.stations: list[dict] = []   # {"tone": float, "last": float}

    def assign(self, tone: float | None, now: float) -> int:
        """Station index for this pitch (0 = the station being worked)."""
        if not tone:
            return 0
        self.stations = [s for s in self.stations if now - s["last"] <= self.ttl] or []
        best, best_d = None, self.tol
        for s in self.stations:
            d = abs(s["tone"] - tone)
            if d <= best_d:
                best, best_d = s, d
        if best is None:
            if len(self.stations) >= self.max:
                best = min(self.stations, key=lambda s: s["last"])
                best["tone"] = tone
            else:
                self.stations.append({"tone": tone, "last": now})
                best = self.stations[-1]
        else:
            best["tone"] += 0.3 * (tone - best["tone"])   # follow slow drift
        best["last"] = now
        return self.stations.index(best)

    def tones(self) -> list[float]:
        return [round(s["tone"], 1) for s in self.stations]


def smooth_tones(tones, window: int = 2) -> list[float | None]:
    """Median-filter the per-character pitches: a single bad measurement (a dit
    buried in noise) must not split a transmission into two stations."""
    vals = list(tones)
    out: list[float | None] = []
    for i, t in enumerate(vals):
        if t is None:
            out.append(None)
            continue
        near = [v for v in vals[max(0, i - window):i + window + 1] if v]
        out.append(round(float(np.median(near)), 1) if near else t)
    return out


def despeckle(stations, min_run: int = 3) -> list[int]:
    """Merge station runs shorter than `min_run` characters into a neighbouring
    run, so one mis-measured character does not start a new station.

    `None` means "pitch unknown"; such characters always follow their neighbours.
    """
    src = list(stations)
    runs: list[list] = []               # [value, start, length]
    for i, v in enumerate(src):
        if runs and runs[-1][0] == v:
            runs[-1][2] += 1
        else:
            runs.append([v, i, 1])
    changed = True
    while changed and len(runs) > 1:
        changed = False
        for k, (val, _start, ln) in enumerate(runs):
            if ln >= min_run and val is not None:
                continue
            before = runs[k - 1] if k > 0 else None
            after = runs[k + 1] if k + 1 < len(runs) else None
            pick = max([r for r in (before, after) if r is not None and r[0] is not None],
                       key=lambda r: r[2], default=None)
            if pick is None:
                continue
            runs[k][0] = pick[0]
            merged = [runs[0]]
            for r in runs[1:]:
                if merged[-1][0] == r[0]:
                    merged[-1][2] += r[2]
                else:
                    merged.append(r)
            runs, changed = merged, True
            break
    out: list[int] = []
    for val, _start, ln in runs:
        out.extend([0 if val is None else val] * ln)
    return out
