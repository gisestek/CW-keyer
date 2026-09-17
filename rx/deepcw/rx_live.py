#!/usr/bin/env python3
"""CW-asema M0-kokeilu: DeepCW-tulkinta reaaliajassa äänikortilta tai WAV-tiedostosta.

Esimerkit:
  python rx_live.py --list-devices
  python rx_live.py --device "DigiRig"                 # kuuntele ja tulkitse
  python rx_live.py --device 3 --record ts515.wav      # tulkitse ja tallenna ääni
  python rx_live.py --wav ts515.wav                    # tiedosto reaaliaikanopeudella
  python rx_live.py --wav ts515.wav --fast             # tiedosto niin nopeasti kuin kone jaksaa

Tulostus: vahvistettu teksti UTC-aikaleimoin, alimmalla rivillä esikatselu
(voi vielä muuttua), tulotaso ja voimakkain äänitaajuus.
--jsonl tallentaa tapahtumat JSON-riveinä (FR-RX-03).

Lisenssi: AGPL-3.0-or-later. Käyttää DeepCW-mallia (e04/deepcw-engine, AGPL-3.0-only).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import queue
import sys
import time
from pathlib import Path

import numpy as np
import soxr

from deepcw_decoder import DeepCWModel, StreamConfig, StreamingDecoder

HERE = Path(__file__).resolve().parent
DEFAULT_ENGINE = HERE.parent.parent / "third_party" / "deepcw-engine"

CLIP_DBFS = -1.0
WEAK_DBFS = -50.0


def utc_iso(t: float) -> str:
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def utc_hms(t: float) -> str:
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%H:%M:%SZ")


class Console:
    def __init__(self, show_pending: bool):
        self.show_pending = show_pending
        self.status = ""
        self.pending = ""
        if os.name == "nt":
            os.system("")  # ANSI-ohjauskoodit päälle Windowsin konsolissa

    def _draw(self):
        if not sys.stdout.isatty():
            return
        line = self.status
        if self.show_pending and self.pending:
            line += "  \x1b[2m" + self.pending[-90:] + "\x1b[0m"
        sys.stdout.write("\r\x1b[2K" + line)
        sys.stdout.flush()

    def final(self, t: float, text: str):
        if sys.stdout.isatty():
            sys.stdout.write("\r\x1b[2K")
        print(f"{utc_hms(t)}  \x1b[1m{text}\x1b[0m" if sys.stdout.isatty() else f"{utc_hms(t)}  {text}")
        self.pending = ""
        self._draw()

    def set_pending(self, text: str):
        self.pending = text
        self._draw()

    def set_status(self, text: str):
        self.status = text
        self._draw()

    def info(self, text: str):
        if sys.stdout.isatty():
            sys.stdout.write("\r\x1b[2K")
        print(text)
        self._draw()


class LevelMeter:
    """Tulotaso (dBFS) ja voimakkain taajuus 300–1500 Hz noin sekunnin jaksoissa."""

    def __init__(self, fs: int):
        self.fs = fs
        self.buf: list[np.ndarray] = []
        self.n = 0

    def add(self, x: np.ndarray):
        self.buf.append(x)
        self.n += len(x)

    def ready(self) -> bool:
        return self.n >= self.fs

    def take(self) -> dict:
        x = np.concatenate(self.buf)
        self.buf, self.n = [], 0
        peak = float(np.max(np.abs(x))) if len(x) else 0.0
        rms = float(np.sqrt(np.mean(x.astype(np.float64) ** 2))) if len(x) else 0.0
        db = lambda v: 20 * np.log10(max(v, 1e-9))
        seg = x[-min(len(x), 8192):]
        spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
        freqs = np.fft.rfftfreq(len(seg), 1 / self.fs)
        band = (freqs >= 300) & (freqs <= 1500)
        tone = float(freqs[band][np.argmax(spec[band])]) if band.any() else 0.0
        return {"peak_dbfs": round(db(peak), 1), "rms_dbfs": round(db(rms), 1), "tone_hz": round(tone)}


def list_devices():
    import sounddevice as sd

    print(sd.query_devices())
    print("\nValitse syöttölaite numerolla tai nimen osalla: --device 3  tai  --device DigiRig")


def main():
    ap = argparse.ArgumentParser(description="DeepCW-tulkinta reaaliajassa (M0-kokeilu)")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--device", help="äänilaite (numero tai nimen osa); oletus = järjestelmän oletuslaite")
    src.add_argument("--wav", type=Path, help="tulkitse ääni tiedostosta")
    ap.add_argument("--list-devices", action="store_true", help="listaa äänilaitteet")
    ap.add_argument("--samplerate", type=int, default=48000, help="äänikortin näytetaajuus (oletus 48000)")
    ap.add_argument("--channel", type=int, default=0, help="käytettävä kanava 0=vasen, 1=oikea")
    ap.add_argument("--fast", action="store_true", help="WAV: älä odota reaaliaikaa")
    ap.add_argument("--record", type=Path, help="tallenna äänikortin ääni WAV-tiedostoon")
    ap.add_argument("--jsonl", type=Path, help="kirjoita tapahtumat JSON-riveinä")
    ap.add_argument("--log", type=Path, help="kirjoita vahvistettu teksti tekstitiedostoon")
    ap.add_argument("--no-pending", action="store_true", help="älä näytä esikatselua")
    ap.add_argument("--engine", type=Path, default=DEFAULT_ENGINE, help="deepcw-engine-kansio (model.onnx)")
    ap.add_argument("--threads", type=int, default=0, help="ONNX-säikeet (0 = automaattinen)")
    args = ap.parse_args()

    if args.list_devices:
        list_devices()
        return

    model_path = args.engine / "model.onnx"
    meta_path = args.engine / "model.onnx.json"
    if not model_path.exists():
        sys.exit(f"Mallia ei löydy: {model_path}\n"
                 f"Hae se:  git clone https://github.com/e04/deepcw-engine \"{args.engine}\"")

    model = DeepCWModel(model_path, meta_path, threads=args.threads)
    decoder = StreamingDecoder(model, StreamConfig())
    con = Console(show_pending=not args.no_pending)
    jsonl = open(args.jsonl, "a", encoding="utf-8") if args.jsonl else None
    textlog = open(args.log, "a", encoding="utf-8") if args.log else None

    def emit(obj: dict):
        if jsonl:
            jsonl.write(json.dumps(obj, ensure_ascii=False) + "\n")
            jsonl.flush()

    # --- lähde ---
    rec = None
    if args.wav:
        import soundfile as sf

        info = sf.info(str(args.wav))
        in_fs = info.samplerate
        wav_iter = sf.blocks(str(args.wav), blocksize=in_fs // 10, dtype="float32", always_2d=True)
        con.info(f"Tiedosto {args.wav.name}: {info.duration:.1f} s, {in_fs} Hz, {info.channels} kanavaa")
        audio_q = None
    else:
        import sounddevice as sd

        in_fs = args.samplerate
        audio_q: queue.Queue = queue.Queue(maxsize=200)
        overflows = {"n": 0}

        def cb(indata, frames, time_info, status):
            if status:
                overflows["n"] += 1
            try:
                audio_q.put_nowait(indata.copy())
            except queue.Full:
                overflows["n"] += 1

        device = args.device
        if device is not None and device.isdigit():
            device = int(device)
        dev_info = sd.query_devices(device, "input")
        channels = max(1, min(int(dev_info["max_input_channels"]), args.channel + 1))
        stream = sd.InputStream(device=device, channels=channels, samplerate=in_fs,
                                dtype="float32", blocksize=in_fs // 20, callback=cb)
        con.info(f"Äänilaite: {dev_info['name']}  ({in_fs} Hz, kanava {args.channel})")
        if args.record:
            import soundfile as sf

            rec = sf.SoundFile(str(args.record), "w", samplerate=in_fs, channels=1, subtype="PCM_16")
            con.info(f"Tallennetaan: {args.record}")

    resampler = soxr.ResampleStream(in_fs, model.sample_rate, 1, dtype="float32", quality="HQ")
    meter = LevelMeter(in_fs)
    t_start = time.time()
    audio_in_s = 0.0
    con.info("Tulkinta käynnissä. Ctrl+C lopettaa.  (Tason tulisi olla noin -30…-10 dBFS, äänen 400–1200 Hz)")
    emit({"ev": "rx_start", "utc": utc_iso(t_start), "source": str(args.wav or args.device or "default"),
          "model": "deepcw-engine", "sample_rate_in": in_fs})

    def handle_events(events, final_flush=False):
        for ev in events:
            if ev.kind == "pending":
                con.set_pending(ev.text)
            else:
                t_utc = t_start + ev.audio_start_s
                con.final(t_utc, ev.text)
                emit({"ev": "rx_text", "utc": utc_iso(t_utc), "audio_start_s": round(ev.audio_start_s, 2),
                      "audio_end_s": round(ev.audio_end_s, 2), "text": ev.text, "final": True})
                if textlog:
                    textlog.write(f"{utc_iso(t_utc)}\tRX\t{ev.text}\n")
                    textlog.flush()

    def process(block: np.ndarray):
        nonlocal audio_in_s
        mono = block[:, min(args.channel, block.shape[1] - 1)]
        if rec is not None:
            rec.write(mono)
        meter.add(mono)
        audio_in_s += len(mono) / in_fs
        if meter.ready():
            lv = meter.take()
            warn = ""
            if lv["peak_dbfs"] > CLIP_DBFS:
                warn = "  \x1b[31mYLIOHJAUS\x1b[0m"
            elif lv["rms_dbfs"] < WEAK_DBFS:
                warn = "  \x1b[33mHEIKKO\x1b[0m"
            elif not 400 <= lv["tone_hz"] <= 1200:
                warn = "  \x1b[33mSÄVEL 400–1200 Hz ULKOPUOLELLA\x1b[0m"
            rtf = decoder.infer_ms_total / 1000 / max(audio_in_s, 1e-6)
            con.set_status(f"[{lv['rms_dbfs']:6.1f} dBFS  huippu {lv['peak_dbfs']:5.1f}  {lv['tone_hz']:4d} Hz  "
                           f"CPU {rtf * 100:4.1f} %]{warn}")
            emit({"ev": "rx_level", "utc": utc_iso(time.time()), **lv})
        handle_events(decoder.feed(resampler.resample_chunk(mono)))

    try:
        if args.wav:
            t0 = time.perf_counter()
            for block in wav_iter:
                process(block)
                if not args.fast:
                    lag = audio_in_s - (time.perf_counter() - t0)
                    if lag > 0:
                        time.sleep(lag)
            handle_events(decoder.feed(resampler.resample_chunk(np.zeros(0, np.float32), last=True)))
            handle_events(decoder.flush())
        else:
            with stream:
                while True:
                    block = audio_q.get()
                    process(block)
    except KeyboardInterrupt:
        pass
    finally:
        handle_events(decoder.flush())
        if sys.stdout.isatty():
            sys.stdout.write("\n")
        calls = max(decoder.infer_calls, 1)
        print(f"Dekoodauksia {decoder.infer_calls}, keskimäärin {decoder.infer_ms_total / calls:.0f} ms, "
              f"CPU-aika {100 * decoder.infer_ms_total / 1000 / max(audio_in_s, 1e-6):.1f} % äänen kestosta")
        if not args.wav and overflows["n"]:
            print(f"Varoitus: äänipuskuri ylittyi {overflows['n']} kertaa")
        emit({"ev": "rx_stop", "utc": utc_iso(time.time())})
        for f in (jsonl, textlog, rec):
            if f:
                f.close()


if __name__ == "__main__":
    main()
