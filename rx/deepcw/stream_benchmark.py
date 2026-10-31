#!/usr/bin/env python3
"""Streaming benchmark of the program's own decoder (cwstation.rx.deepcw), for comparing models.

Runs synthetic QSO text through StreamingDecoder exactly like the program does (3200 Hz, 50 ms
chunks) and reports the character error rate per condition, phantom characters per minute of
pure noise, and CPU time relative to the audio length.

    python rx/deepcw/stream_benchmark.py                                   # model in third_party
    python rx/deepcw/stream_benchmark.py --engine path/to/old/model --min-conf 0.8

Run from the repository root. Results of 2026-10-31 (v1 vs v2): rx/deepcw/README.md.
Lisenssi: AGPL-3.0-or-later.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "rx" / "deepcw"))

import cwstation.rx.deepcw as dc  # noqa: E402
from cwgen import random_qso_text  # noqa: E402
from cwstation.rx.cwgen import cw_audio  # noqa: E402


def levenshtein(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def stream(model: dc.DeepCWModel, audio: np.ndarray) -> tuple[str, float]:
    sd = dc.StreamingDecoder(model)
    out: list[str] = []
    t0 = time.process_time()
    for i in range(0, len(audio), 160):
        out += [e.text for e in sd.feed(audio[i:i + 160]) if e.kind == "final"]
    out += [e.text for e in sd.flush() if e.kind == "final"]
    return " ".join(" ".join(out).split()), time.process_time() - t0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", type=Path, default=ROOT / "third_party" / "deepcw-engine")
    ap.add_argument("--min-conf", type=float, default=None, help="override MIN_CHAR_CONFIDENCE")
    ap.add_argument("--seeds", type=int, default=3)
    args = ap.parse_args()
    if args.min_conf is not None:
        dc.MIN_CHAR_CONFIDENCE = args.min_conf
    m = dc.DeepCWModel(args.engine / "model.onnx", args.engine / "model.onnx.json", threads=1)
    res: dict = {"engine": str(args.engine), "min_conf": dc.MIN_CHAR_CONFIDENCE, "cer_pct": {}}
    cpu = audio_s = 0.0
    for cond, qsb, jitter in (("flat", 0, 0.0), ("qsb10+hand10%", 10, 0.10)):
        for snr in (0, -6, -9, -12, -15):
            errs = n = 0
            for seed in range(args.seeds):
                for wpm in (18, 26):
                    text = " ".join(random_qso_text(np.random.default_rng(seed * 100 + wpm)).split()[:18])
                    a = cw_audio(text, wpm=wpm, fs=3200, snr_db=snr, qsb_db=qsb, jitter=jitter, seed=seed,
                                 tone_hz=600 + 50 * seed)
                    hyp, c = stream(m, a)
                    cpu += c
                    audio_s += len(a) / 3200
                    errs += levenshtein(text, hyp)
                    n += len(text)
            res["cer_pct"][f"{cond} {snr:+d} dB"] = round(100 * errs / n, 1)
            print(f"{cond:14s} {snr:+3d} dB  CER {res['cer_pct'][f'{cond} {snr:+d} dB']:5.1f} %", flush=True)
    phantoms = 0
    for seed in range(5):
        noise = np.random.default_rng(1000 + seed).normal(0, 0.05, 3200 * 60).astype(np.float32)
        hyp, _ = stream(m, noise)
        phantoms += len(hyp.replace(" ", ""))
    res["phantom_chars_per_min"] = round(phantoms / 5, 2)
    res["cpu_pct"] = round(100 * cpu / audio_s, 1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
