"""ADIF 3.x helpers: field formatting, band lookup and appending QSOs to a .adi file."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from .. import APP_NAME, __version__

ADIF_VER = "3.1.4"

# IARU region 1 amateur bands (MHz); enough for band lookup from a frequency.
BANDS: list[tuple[str, float, float]] = [
    ("2190m", 0.1357, 0.1378), ("630m", 0.472, 0.479), ("160m", 1.8, 2.0), ("80m", 3.5, 4.0),
    ("60m", 5.06, 5.45), ("40m", 7.0, 7.3), ("30m", 10.1, 10.15), ("20m", 14.0, 14.35),
    ("17m", 18.068, 18.168), ("15m", 21.0, 21.45), ("12m", 24.89, 24.99), ("10m", 28.0, 29.7),
    ("6m", 50.0, 54.0), ("4m", 70.0, 71.0), ("2m", 144.0, 148.0), ("70cm", 430.0, 450.0),
]


def band_for(freq_mhz: float | None) -> str:
    if not freq_mhz:
        return ""
    for name, lo, hi in BANDS:
        if lo <= freq_mhz <= hi:
            return name
    return ""


def field(name: str, value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    return f"<{name.upper()}:{len(text.encode('utf-8'))}>{text} "


def qso_to_adif(qso: dict) -> str:
    """qso: keys call, qso_date (YYYYMMDD), time_on/time_off (HHMMSS), freq_mhz, mode, rst_sent…"""
    freq = qso.get("freq_mhz")
    parts = [
        field("call", (qso.get("call") or "").upper()),
        field("qso_date", qso.get("qso_date")),
        field("time_on", qso.get("time_on")),
        field("time_off", qso.get("time_off")),
        field("band", qso.get("band") or band_for(freq)),
        field("freq", f"{float(freq):.6f}" if freq else ""),
        field("mode", qso.get("mode") or "CW"),
        field("rst_sent", qso.get("rst_sent")),
        field("rst_rcvd", qso.get("rst_rcvd")),
        field("name", qso.get("name")),
        field("qth", qso.get("qth")),
        field("gridsquare", qso.get("gridsquare")),
        field("tx_pwr", qso.get("tx_pwr")),
        field("comment", qso.get("comment")),
        field("station_callsign", (qso.get("station_callsign") or "").upper()),
        field("operator", (qso.get("operator") or "").upper()),
        field("my_gridsquare", qso.get("my_gridsquare")),
    ]
    return "".join(p for p in parts if p).strip() + " <EOR>"


def header() -> str:
    now = dt.datetime.now(dt.timezone.utc)
    return (f"{APP_NAME} ADIF export\n"
            f"{field('adif_ver', ADIF_VER)}{field('programid', APP_NAME)}"
            f"{field('programversion', __version__)}{field('created_timestamp', now.strftime('%Y%m%d %H%M%S'))}"
            "<EOH>\n")


def append_qso(path: Path, qso: dict) -> str:
    """Append one QSO to an .adi file (creating it with a header). Returns the ADIF record."""
    record = qso_to_adif(qso)
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists() or path.stat().st_size == 0
    with open(path, "a", encoding="utf-8") as f:
        if new:
            f.write(header())
        f.write(record + "\n")
    return record
