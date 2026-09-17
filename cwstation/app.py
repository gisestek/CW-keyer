"""Station: wires the modules together and owns start-up and shutdown safety.

Kept free of GUI code so that closing or crashing the window can never leave
the key down (SR-04, SR-05) and so the same core can later run headless.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from .core.bus import Bus
from .core.resources import model_dir
from .core.settings import Settings
from .core.textlog import TextLog
from .rx.audio import SoundCardSource, WavSource
from .rx.rx_module import RxModule
from .tx.keyer_client import KeyerClient
from .tx.tx_module import TxModule

log = logging.getLogger(__name__)

KEYER_SET_KEYS = ("wpm", "weight", "keydown_max_ms", "tx_max_ms", "heartbeat_ms")


class Station:
    def __init__(self, settings: Settings, wav: Path | None = None, sim_keyer: bool = False,
                 bus: Bus | None = None):
        self.settings = settings
        self.bus = bus or Bus()
        self.wav = wav
        self.sim_keyer = sim_keyer
        self._sim = None
        self._ticker_stop = threading.Event()

        if sim_keyer:
            from .tx import keyer_sim

            self._sim = keyer_sim.start_in_thread()
            url = f"ws://127.0.0.1:{self._sim['port']}/"
        else:
            url = settings.get("keyer.url")
        initial = {k: settings.get(f"keyer.{k}") for k in KEYER_SET_KEYS}
        self.keyer = KeyerClient(self.bus, url, initial_set=initial, simulated=sim_keyer)
        self.tx = TxModule(self.bus, settings, self.keyer)
        self.textlog = TextLog(self.bus, settings.log_folder(), float(settings.get("log.line_pause_s", 3.0)))
        self.rx = RxModule(self.bus, model_dir(), self._make_source)
        self._shutdown_done = False

    def _make_source(self):
        if self.wav:
            return WavSource(self.wav, loop=True, realtime=True)
        return SoundCardSource(self.settings.get("audio.device", ""),
                               int(self.settings.get("audio.samplerate", 48000)),
                               int(self.settings.get("audio.channel", 0)))

    def start(self) -> None:
        self.keyer.start()
        self.rx.start()
        threading.Thread(target=self._tick, name="ticker", daemon=True).start()

    def _tick(self) -> None:
        while not self._ticker_stop.wait(1.0):
            self.textlog.tick()

    def apply_settings(self, old: dict) -> None:
        """Called after the settings dialog was accepted (settings already updated)."""
        s = self.settings
        if old.get("audio") != s.get("audio") and not self.wav:
            self.rx.restart()
        if not self.sim_keyer and old.get("keyer", {}).get("url") != s.get("keyer.url"):
            self.keyer.set_url(s.get("keyer.url"))
        new_set = {k: s.get(f"keyer.{k}") for k in KEYER_SET_KEYS}
        old_set = {k: old.get("keyer", {}).get(k) for k in KEYER_SET_KEYS}
        if new_set != old_set:
            self.keyer.initial_set.update(new_set)
            self.keyer.send({"cmd": "set", **new_set})
        self.textlog.flush()
        self.textlog.folder = s.log_folder()
        self.textlog.line_pause_s = float(s.get("log.line_pause_s", 3.0))
        s.save()

    def shutdown(self) -> None:
        """STOP first, then close everything (SR-05). Safe to call more than once."""
        if self._shutdown_done:
            return
        self._shutdown_done = True
        log.info("shutdown: sending STOP")
        try:
            self.bus.publish("tx.stop", reason="shutdown")
        finally:
            self.keyer.shutdown()
            self._ticker_stop.set()
            self.rx.stop()
            self.textlog.flush()
            try:
                self.settings.save()
            except OSError:
                log.exception("could not save settings")
