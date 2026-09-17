"""Synteettinen CW-äänigeneraattori testejä varten (kohina, QSB, käsiavainnuksen epätarkkuus).

SNR määritellään kuten DeepCW:n benchmarkissa: signaalin keskiteho koko
äänitteen yli (noin 50 % avainnussuhde) suhteessa kohinaan 2500 Hz:n kaistassa.

Lisenssi: AGPL-3.0-or-later.
"""
from __future__ import annotations

import numpy as np

MORSE = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.", "G": "--.", "H": "....",
    "I": "..", "J": ".---", "K": "-.-", "L": ".-..", "M": "--", "N": "-.", "O": "---", "P": ".--.",
    "Q": "--.-", "R": ".-.", "S": "...", "T": "-", "U": "..-", "V": "...-", "W": ".--", "X": "-..-",
    "Y": "-.--", "Z": "--..", "0": "-----", "1": ".----", "2": "..---", "3": "...--", "4": "....-",
    "5": ".....", "6": "-....", "7": "--...", "8": "---..", "9": "----.", ".": ".-.-.-", ",": "--..--",
    "?": "..--..", "/": "-..-.",
}


def keying_envelope(text: str, wpm: float, fs: int, jitter: float = 0.0,
                    rise_ms: float = 5.0, rng: np.random.Generator | None = None,
                    lead_s: float = 0.5, tail_s: float = 0.5, word_ends: list | None = None) -> np.ndarray:
    rng = rng or np.random.default_rng()
    unit = 1.2 / wpm
    segs: list[tuple[float, int]] = [(lead_s, 0)]

    def j(d: float) -> float:
        return max(d * (1 + rng.normal(0, jitter)), unit * 0.3) if jitter else d

    for wi, word in enumerate(text.upper().split()):
        if wi:
            segs.append((j(7 * unit), 0))
        for ci, ch in enumerate(word):
            code = MORSE.get(ch)
            if not code:
                continue
            if ci:
                segs.append((j(3 * unit), 0))
            for ei, sym in enumerate(code):
                if ei:
                    segs.append((j(unit), 0))
                segs.append((j(unit if sym == "." else 3 * unit), 1))
        if word_ends is not None:
            word_ends.append(sum(d for d, _ in segs))
    segs.append((tail_s, 0))
    total = int(sum(d for d, _ in segs) * fs) + 1
    env = np.zeros(total, dtype=np.float32)
    pos = 0.0
    for d, on in segs:
        a, b = int(pos * fs), int((pos + d) * fs)
        if on:
            env[a:b] = 1.0
        pos += d
    # pehmeät reunat (raised cosine), estää avainnusnaksut
    r = max(1, int(rise_ms / 1000 * fs))
    k = np.hanning(2 * r + 1).astype(np.float32)
    k /= k.sum()
    return np.convolve(env, k, mode="same").astype(np.float32)


def cw_audio(text: str, wpm: float = 20, fs: int = 48000, tone_hz: float = 700,
             snr_db: float | None = 10, qsb_db: float = 0.0, qsb_hz: float = 0.2,
             jitter: float = 0.0, seed: int | None = None, word_ends: list | None = None) -> np.ndarray:
    rng = np.random.default_rng(seed)
    env = keying_envelope(text, wpm, fs, jitter, rng=rng, word_ends=word_ends)
    t = np.arange(len(env)) / fs
    sig = env * np.sin(2 * np.pi * tone_hz * t + rng.uniform(0, 2 * np.pi))
    if qsb_db:
        depth = 10 ** (-qsb_db / 20)
        fade = depth + (1 - depth) * 0.5 * (1 + np.sin(2 * np.pi * qsb_hz * t + rng.uniform(0, 6.28)))
        sig *= fade
    sig = sig.astype(np.float32)
    if snr_db is None:
        out = 0.3 * sig
    else:
        p_sig = float(np.mean(sig ** 2))
        p_noise_2500 = p_sig / (10 ** (snr_db / 10))
        sigma2 = p_noise_2500 * (fs / 2) / 2500.0     # valkoinen kohina koko kaistalla
        noise = rng.normal(0, np.sqrt(sigma2), len(sig)).astype(np.float32)
        out = sig + noise
        out *= 0.3 / max(1e-9, float(np.percentile(np.abs(out), 99.9)))
    return out.astype(np.float32)


CALLS = ["OH2BH", "OH6XY", "DL1ABC", "SM5QRS", "G4XYZ", "K1ABC", "JA1XYZ", "OH1AA", "ES5RY", "LY2ZZ"]
NAMES = ["JUKKA", "PEKKA", "HANS", "JOHN", "OLA", "MATTI", "TOM"]
QTHS = ["HELSINKI", "OULU", "BERLIN", "STOCKHOLM", "TALLINN", "LONDON"]


def random_qso_text(rng: np.random.Generator, words: int = 12) -> str:
    c1, c2 = rng.choice(CALLS, 2, replace=False)
    parts = [
        f"CQ CQ DE {c1} {c1} K",
        f"{c1} DE {c2} GM UR RST 5{rng.integers(3, 10)}9 5NN",
        f"NAME {rng.choice(NAMES)} QTH {rng.choice(QTHS)} HW? {c1} DE {c2} K",
        f"R TNX FER QSO 73 {c2} DE {c1} SK",
        f"RIG {rng.integers(100, 999)}W ANT DIPOLE WX CLOUDY {rng.integers(1, 30)}C",
    ]
    text = " ".join(parts)
    return " ".join(text.split()[:words])
