"""Settings stored as human-readable JSON (FR-CORE-01, NFR-07).

Windows: %APPDATA%\\CWStation\\settings.json
Linux:   ~/.config/CWStation/settings.json
"""
from __future__ import annotations

import copy
import json
import logging
import os
import sys
import threading
from pathlib import Path

from .. import APP_ID

log = logging.getLogger(__name__)

DEFAULTS: dict = {
    "station": {"callsign": "", "name": "", "qth": "", "locator": ""},
    "audio": {"device": "", "channel": 0, "samplerate": 48000},
    "keyer": {
        "type": "wifi",              # "wifi" = WebSocket keyer, "winkeyer" = serial WinKeyer
        "serial_port": "",           # COM port of the WinKeyer, e.g. "COM5" or "/dev/ttyUSB0"
        "url": "ws://cwkeyer.local:81/",
        "wpm": 20,
        "weight": 50,
        "keydown_max_ms": 10500,
        "tx_max_ms": 120000,
        "heartbeat_ms": 3000,
    },
    "log": {"folder": "", "line_pause_s": 3.0},
    "ui": {"language": "en", "font_size": 13, "window": None, "waterfall_seconds": 12, "splitter": None},
    "macros": {
        "F1": {"label": "CQ", "text": "CQ CQ CQ DE {MYCALL} {MYCALL} K"},
        "F2": {"label": "MYCALL", "text": "{MYCALL}"},
        "F3": {"label": "73", "text": "TU 73 DE {MYCALL} <SK>"},
        "F4": {"label": "Answer", "text": "{CALL} DE {MYCALL} {MYCALL} K"},
        "F5": {"label": "Report", "text": "{CALL} DE {MYCALL} UR RST {RST} {RST} NAME {MYNAME} {MYNAME} QTH {MYQTH} HW? {CALL} DE {MYCALL} K"},
        "F6": {"label": "QSL", "text": "R R TNX FER QSO DR {NAME} 73 ES CUL {CALL} DE {MYCALL} <SK>"},
    },
    "qso": {"freq_mhz": 7.03, "tx_pwr": "100", "adif_file": ""},
    "cq": {"interval_s": 8, "macro": "F1"},
    "wavelog": {"enabled": False, "url": "", "key": "", "station_profile_id": ""},
}


def config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / APP_ID


def default_log_folder() -> Path:
    docs = Path.home() / "Documents"
    return (docs if docs.exists() else Path.home()) / APP_ID / "logs"


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


class Settings:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (config_dir() / "settings.json")
        self._lock = threading.RLock()
        self.data = copy.deepcopy(DEFAULTS)
        self.load()

    def load(self) -> None:
        with self._lock:
            if self.path.exists():
                try:
                    self.data = _merge(DEFAULTS, json.loads(self.path.read_text(encoding="utf-8")))
                except (OSError, ValueError):
                    log.exception("settings file unreadable, using defaults: %s", self.path)
                    self.data = copy.deepcopy(DEFAULTS)

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)

    def get(self, dotted: str, default=None):
        with self._lock:
            node = self.data
            for part in dotted.split("."):
                if not isinstance(node, dict) or part not in node:
                    return default
                node = node[part]
            return copy.deepcopy(node)

    def set(self, dotted: str, value) -> None:
        with self._lock:
            parts = dotted.split(".")
            node = self.data
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = value

    def log_folder(self) -> Path:
        folder = self.get("log.folder") or ""
        return Path(folder) if folder else default_log_folder()
