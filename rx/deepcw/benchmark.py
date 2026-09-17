#!/usr/bin/env python3
"""DeepCW M0-benchmark synteettisellä CW:llä: merkkivirhe (CER), viive ja CPU.

Ajaa saman äänen sekä kokonaisena (malli näkee koko pätkän) että striimaavan
dekooderin läpi simuloidussa reaaliajassa, ja mittaa:
  - CER: merkkivirheet suhteessa lähetettyyn tekstiin (välilyönnit mukana)
  - viive: kuinka kauan sanan viimeisen merkin jälkeen sana näkyy
      esikatselussa (FR-RX-02: < 2 s) ja vahvistettuna tekstinä
  - CPU: dekoodausaika / äänen kesto (NFR-03)

Käyttö:  python benchmark.py [--quick] [--engine polku]
Lisenssi: AGPL-3.0-or-later.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
import soxr

from cwgen import cw_audio, random_qso_text
from deepcw_decoder import DeepCWModel, StreamConfig, StreamingDecoder, normalize_text

HERE = Path(__file__).resolve().parent


def levenshtein(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def cer(ref: str, hyp: str) -> float:
    ref, hyp = normalize_text(ref), normalize_text(hyp)
    return levenshtein(ref, hyp) / max(1, len(ref))


def words_present(ref_words: list[str], hyp: str) -> int:
    """Montako viitetekstin sanaa löytyy järjestyksessä hypoteesista (sallii virheet väleissä)."""
    hyp_words = hyp.split()
    k = 0
    for w in hyp_words:
        if k < len(ref_words) and w == ref_words[k]:
            k += 1
        elif k + 1 < len(ref_words) and w == ref_words[k + 1]:
            k += 2  # yksi sana tulkittu väärin, jatketaan
    return k


def run_case(model: DeepCWModel, text: str, wpm: float, snr: float, qsb: float, jitter: float, seed: int,
             fs_in: int = 48000, chunk_s: float = 0.05):
    word_ends: list[float] = []
    audio = cw_audio(text, wpm=wpm, fs=fs_in, snr_db=snr, qsb_db=qsb, jitter=jitter, seed=seed,
                     tone_hz=650 + (seed % 5) * 50, word_ends=word_ends)
    a3 = soxr.resample(audio, fs_in, model.sample_rate)
    dur = len(a3) / model.sample_rate

    # vertailu: kiinteät 20 s palat ilman striimauslogiikkaa (katkeaa kesken merkkien)
    whole = []
    step = 20 * model.sample_rate
    for i in range(0, len(a3), step):
        whole.append(model.decode(a3[i:i + step]).text)
    whole_text = normalize_text(" ".join(whole))

    # striimaten
    sd = StreamingDecoder(model, StreamConfig())
    rs = soxr.ResampleStream(fs_in, model.sample_rate, 1, dtype="float32")
    ref_words = normalize_text(text).split()
    finals: list[str] = []
    pending = ""
    first_pending = [None] * len(ref_words)
    first_final = [None] * len(ref_words)
    n = int(chunk_s * fs_in)
    t_audio = 0.0
    for i in range(0, len(audio), n):
        for ev in sd.feed(rs.resample_chunk(audio[i:i + n])):
            if ev.kind == "pending":
                pending = ev.text
            else:
                finals.append(ev.text)
                pending = ""
        t_audio = min(len(audio), i + n) / fs_in
        final_text = " ".join(finals)
        kp = words_present(ref_words, final_text + " " + pending)
        kf = words_present(ref_words, final_text)
        for k in range(kp):
            if first_pending[k] is None:
                first_pending[k] = t_audio
        for k in range(kf):
            if first_final[k] is None:
                first_final[k] = t_audio
    for ev in sd.feed(rs.resample_chunk(np.zeros(0, np.float32), last=True)) + sd.flush():
        if ev.kind == "final":
            finals.append(ev.text)
    stream_text = normalize_text(" ".join(finals))

    lat_p = [fp - we for fp, we in zip(first_pending, word_ends) if fp is not None]
    lat_f = [ff - we for ff, we in zip(first_final, word_ends) if ff is not None]
    return {
        "dur": dur,
        "cer_whole": cer(text, whole_text),
        "cer_stream": cer(text, stream_text),
        "lat_pending": lat_p,
        "lat_final": lat_f,
        "infer_ms": sd.infer_ms_total,
        "stream_text": stream_text,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", type=Path, default=HERE.parent.parent / "third_party" / "deepcw-engine")
    ap.add_argument("--quick", action="store_true", help="vain muutama tapaus")
    ap.add_argument("--threads", type=int, default=0)
    args = ap.parse_args()
    model = DeepCWModel(args.engine / "model.onnx", args.engine / "model.onnx.json", threads=args.threads)

    rng = np.random.default_rng(2026)
    wpms = [15, 25] if args.quick else [12, 18, 25, 32]
    snrs = [10, 0, -6] if args.quick else [10, 0, -6, -9, -12]
    reps = 1 if args.quick else 2
    conditions = [("puhdas ajoitus", 0.0, 0.0), ("QSB 10 dB + käsiavain 10 %", 10.0, 0.10)]

    print(f"{'olosuhde':28s} {'WPM':>4s} {'SNR':>5s} | {'CER 20s-palat':>13s} {'CER striimi':>11s} | "
          f"{'esikatselu p50/p90 s':>20s} {'vahvistus p50/p90 s':>20s}")
    all_p, all_f, total_ms, total_dur = [], [], 0.0, 0.0
    t0 = time.time()
    for cname, qsb, jit in conditions:
        for wpm in wpms:
            for snr in snrs:
                cw, cs, lp, lf = [], [], [], []
                for r in range(reps):
                    text = random_qso_text(rng, words=40)
                    res = run_case(model, text, wpm, snr, qsb, jit, seed=int(rng.integers(1e6)))
                    cw.append(res["cer_whole"]); cs.append(res["cer_stream"])
                    lp += res["lat_pending"]; lf += res["lat_final"]
                    total_ms += res["infer_ms"]; total_dur += res["dur"]
                all_p += lp; all_f += lf
                q = lambda v, p: np.percentile(v, p) if v else float("nan")
                print(f"{cname:28s} {wpm:4d} {snr:5d} | {100*np.mean(cw):12.1f}% {100*np.mean(cs):10.1f}% | "
                      f"{q(lp,50):9.2f} /{q(lp,90):6.2f}      {q(lf,50):9.2f} /{q(lf,90):6.2f}")
    print()
    print(f"Viive kaikki: esikatselu p50 {np.percentile(all_p,50):.2f} s, p90 {np.percentile(all_p,90):.2f} s, "
          f"osuus < 2 s {100*np.mean(np.array(all_p) < 2):.0f} %")
    print(f"              vahvistus  p50 {np.percentile(all_f,50):.2f} s, p90 {np.percentile(all_f,90):.2f} s")
    print(f"CPU: striimidekoodaus {100*total_ms/1000/total_dur:.1f} % äänen kestosta "
          f"({total_dur/60:.1f} min ääntä, ajo {time.time()-t0:.0f} s)")


if __name__ == "__main__":
    main()
