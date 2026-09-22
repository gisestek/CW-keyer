"""Station: wires the modules together and owns start-up and shutdown safety.

Kept free of GUI code so that closing or crashing the window can never leave
the key down (SR-04, SR-05) and so the same core can later run headless.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from .core import adif
from .core.bus import Bus
from .core.qso import QsoSession
from .core.resources import model_dir
from .core.settings import Settings, config_dir
from .core.textlog import TextLog
from .core.txwindows import TxWindows
from .core.wavelog import WavelogClient
from .rx.audio import SimulatedRadioSource, SoundCardSource, WavSource
from .rx.rx_module import RxModule
from .tx.cq import CqRepeater
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
        self._sim_url = ""
        self._ticker_stop = threading.Event()

        if sim_keyer:
            from .tx import keyer_sim

            self._sim = keyer_sim.start_in_thread()
            self._sim_url = f"ws://127.0.0.1:{self._sim['port']}/"
        self.keyer = self._make_keyer()
        self.qso = QsoSession(self.bus, settings)
        self.tx = TxModule(self.bus, settings, self.keyer, qso=self.qso)
        self.tx_windows = TxWindows(self.bus)
        self.cq = CqRepeater(self.bus, settings)
        self.wavelog = WavelogClient(self.bus, settings, config_dir() / "wavelog-queue.jsonl")
        self.textlog = TextLog(self.bus, settings.log_folder(), float(settings.get("log.line_pause_s", 3.0)))
        self.rx = RxModule(self.bus, model_dir(), self._make_source, tx_windows=self.tx_windows)
        self._shutdown_done = False

    def keyer_type(self) -> str:
        """`wifi` = own WebSocket keyer, `winkeyer` = serial WinKeyer (FR-TX-08)."""
        if self.sim_keyer:
            return "wifi"
        return "winkeyer" if self.settings.get("keyer.type") == "winkeyer" else "wifi"

    def _make_keyer(self):
        initial = {k: self.settings.get(f"keyer.{k}") for k in KEYER_SET_KEYS}
        if self.keyer_type() == "winkeyer":
            from .tx.winkeyer_client import WinkeyerClient

            return WinkeyerClient(self.bus, self.settings.get("keyer.serial_port", ""),
                                  initial_set=initial)
        url = self._sim_url if self.sim_keyer else self.settings.get("keyer.url")
        return KeyerClient(self.bus, url, initial_set=initial, simulated=self.sim_keyer)

    def _swap_keyer(self) -> None:
        """Keyer type changed in the settings: close the old one and start the new one."""
        old = self.keyer
        try:
            old.shutdown()
        except Exception:  # noqa: BLE001
            log.exception("closing the old keyer failed")
        self.keyer = self._make_keyer()
        self.tx.client = self.keyer
        self.keyer.start()

    def _make_source(self):
        if self.sim_keyer and self._sim:
            return SimulatedRadioSource(self._sim["sim"], self.wav)
        if self.wav:
            return WavSource(self.wav, loop=True, realtime=True)
        return SoundCardSource(self.settings.get("audio.device", ""),
                               int(self.settings.get("audio.samplerate", 48000)),
                               int(self.settings.get("audio.channel", 0)))

    def adif_path(self) -> Path:
        custom = self.settings.get("qso.adif_file") or ""
        return Path(custom) if custom else self.settings.log_folder() / "cwstation.adi"

    def log_qso(self, freq_mhz: float | None = None, tx_pwr: str = "", to_wavelog: bool | None = None) -> dict:
        """Write the current QSO to the ADIF file and (optionally) send it to Wavelog (UC6)."""
        if freq_mhz is None:
            freq_mhz = float(self.settings.get("qso.freq_mhz") or 0) or None
        record = self.qso.to_adif_dict(freq_mhz, tx_pwr or str(self.settings.get("qso.tx_pwr", "")))
        path = self.adif_path()
        text = adif.append_qso(path, record)
        log.info("QSO logged: %s -> %s", record.get("call"), path)
        send = self.wavelog.enabled() if to_wavelog is None else to_wavelog
        if send:
            self.wavelog.send(text, record.get("call", ""))
        self.bus.publish("qso.logged", call=record.get("call", ""), path=str(path), adif=text, wavelog=send)
        self.qso.clear()
        return record

    def start(self) -> None:
        self.wavelog.start()
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
        okeyer = old.get("keyer", {})
        if not self.sim_keyer and okeyer.get("type", "wifi") != s.get("keyer.type", "wifi"):
            self._swap_keyer()
        elif not self.sim_keyer and self.keyer_type() == "winkeyer":
            if okeyer.get("serial_port") != s.get("keyer.serial_port"):
                self.keyer.set_url(s.get("keyer.serial_port", ""))
        elif not self.sim_keyer and okeyer.get("url") != s.get("keyer.url"):
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
        self.cq.stop("shutdown")
        self.wavelog.stop()
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
