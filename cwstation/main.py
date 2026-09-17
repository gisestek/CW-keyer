"""Entry point:  python -m cwstation  (or CWStation.exe)

Developer options (not needed at the station):
  --sim-keyer      use the built-in keyer simulator (nothing is keyed)
  --wav FILE       use a WAV file (looped, real time) instead of the sound card
  --settings FILE  use another settings file
  --selftest SEC   start, send a test text to the simulator, exit with 0 if RX and TX worked
"""
from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import sys
from pathlib import Path


def _setup_logging() -> Path:
    from .core.settings import config_dir

    folder = config_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "cwstation.log"
    handler = logging.handlers.RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    logging.getLogger("websockets").setLevel(logging.WARNING)
    root.addHandler(handler)
    if sys.stderr:
        root.addHandler(logging.StreamHandler())
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="CWStation")
    ap.add_argument("--sim-keyer", action="store_true")
    ap.add_argument("--wav", type=Path)
    ap.add_argument("--settings", type=Path)
    ap.add_argument("--selftest", type=float, metavar="SEC")
    args = ap.parse_args(argv)

    log_path = _setup_logging()
    log = logging.getLogger("cwstation")

    from PySide6.QtWidgets import QApplication

    from . import APP_NAME, __version__
    from .app import Station
    from .core import i18n
    from .core.settings import Settings
    from .gui.main_window import MainWindow

    if args.selftest:
        args.sim_keyer = True
        if not args.wav:
            args.wav = _selftest_wav()
        if not args.settings:
            import tempfile

            args.settings = Path(tempfile.gettempdir()) / "cwstation_selftest_settings.json"
    settings = Settings(args.settings) if args.settings else Settings()
    i18n.load(settings.get("ui.language", "en"))
    log.info("%s %s starting, settings=%s, log=%s", APP_NAME, __version__, settings.path, log_path)

    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    station = Station(settings, wav=args.wav, sim_keyer=args.sim_keyer)
    win = MainWindow(station)
    app.aboutToQuit.connect(station.shutdown)
    station.start()
    win.show()

    if args.selftest:
        return _selftest(app, station, win, args.selftest)
    return app.exec()


def _selftest_wav() -> Path:
    import tempfile

    import soundfile as sf

    from .rx.cwgen import cw_audio

    path = Path(tempfile.gettempdir()) / "cwstation_selftest.wav"
    audio = cw_audio("CQ CQ TEST DE OH0SELF OH0SELF K", wpm=22, fs=48000, snr_db=10, seed=1)
    sf.write(str(path), audio, 48000, subtype="PCM_16")
    return path


def _selftest(app, station, win, seconds: float) -> int:
    """Automated smoke test used by the build: TX echo through the simulator + model load."""
    from PySide6.QtCore import QTimer

    seen = {"echo": "", "rx_status": None, "rx": ""}
    station.bus.subscribe("rx.text", lambda m: seen.__setitem__("rx", seen["rx"] + " " + m["text"]))
    station.bus.subscribe("tx.echo", lambda m: seen.__setitem__("echo", seen["echo"] + m["ch"]))
    station.bus.subscribe("rx.status", lambda m: seen.__setitem__("rx_status", m["state"] + ":" + m.get("msg", "")))

    def send():
        if station.settings.get("station.callsign") in ("", None):
            station.settings.set("station.callsign", "SELFTEST")
        station.bus.publish("tx.set", wpm=40)
        station.bus.publish("tx.send", text="TEST")

    QTimer.singleShot(2500, send)
    QTimer.singleShot(int(seconds * 1000), win.close)
    app.exec()
    ok_tx = "TEST" in seen["echo"]
    ok_rx = "OH0SELF" in seen["rx"]
    result = (f"SELFTEST tx_echo={seen['echo']!r} rx_status={seen['rx_status']!r} rx_text={seen['rx'].strip()!r} "
              f"-> {'OK' if ok_tx and ok_rx else 'FAIL'}")
    print(result)  # no console in the windowed .exe: also write a file
    try:
        from .core.settings import config_dir

        (config_dir() / "selftest-result.txt").write_text(result + "\n", encoding="utf-8")
    except OSError:
        pass
    return 0 if ok_tx and ok_rx else 1


if __name__ == "__main__":
    sys.exit(main())
