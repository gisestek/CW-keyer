"""Macro text expansion and CW text sanitising."""
from __future__ import annotations

import re

# Characters the keyer firmware (PROTOCOL.md v1) can send.
CW_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.,?/=+-()\"':;@! <>")


def expand(text: str, variables: dict[str, str]) -> str:
    """Replace {MYCALL}, {CALL}, {NAME}, {RST} … (case-insensitive). Unknown variables become empty."""
    def rep(m: re.Match) -> str:
        return str(variables.get(m.group(1).upper(), ""))
    return re.sub(r"\{([A-Za-z_]+)\}", rep, text)


def sanitize(text: str) -> tuple[str, str]:
    """Upper-case, whitespace -> single spaces, drop unsupported characters.

    Returns (clean_text, dropped_characters).
    """
    out, dropped = [], []
    for ch in " ".join(text.upper().split()):
        if ch in CW_CHARS:
            out.append(ch)
        else:
            dropped.append(ch)
    clean = "".join(out)
    # an unmatched '<' would glue the rest of the text into one prosign
    if clean.count("<") != clean.count(">"):
        dropped.extend(c for c in clean if c in "<>")
        clean = clean.replace("<", "").replace(">", "")
    return clean, "".join(dropped)


def station_variables(settings) -> dict[str, str]:
    st = settings.get("station", {}) or {}
    return {
        "MYCALL": (st.get("callsign") or "").upper(),
        "MYNAME": (st.get("name") or "").upper(),
        "MYQTH": (st.get("qth") or "").upper(),
        "MYLOC": (st.get("locator") or "").upper(),
    }
