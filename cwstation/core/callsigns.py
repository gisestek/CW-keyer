"""Finding callsigns in decoded text (FR-CORE-03)."""
from __future__ import annotations

import re

# prefix/ + 1–2 letters + digit + 1–4 letters + /suffix
CALL_RE = re.compile(r"\b(?:[A-Z0-9]{1,4}/)?[A-Z]{1,2}[0-9][A-Z]{1,4}(?:/[A-Z0-9]{1,4})?\b")

# things that match the pattern but are not callsigns in a CW QSO
NOT_CALLS = {"CQ", "DE", "K", "KN", "SK", "AR", "BK", "TU", "RST", "QTH", "QRZ", "QSL", "PSE",
             "5NN", "599", "73", "88", "QRP", "QRM", "QRN", "QSB", "WX", "RIG", "ANT", "HW", "UR",
             "R5NN", "S9", "OM", "YL", "ES", "GM", "GA", "GE", "TNX", "FB", "CUL", "AGN", "ABT"}


def find_callsigns(text: str) -> list[tuple[int, int, str]]:
    """Returns [(start, end, call)] for likely callsigns, in order."""
    out = []
    for m in CALL_RE.finditer(text.upper()):
        call = m.group(0)
        if call in NOT_CALLS or len(call) < 3:
            continue
        if not any(c.isdigit() for c in call) or not any(c.isalpha() for c in call):
            continue
        base = call.split("/")[-1] if len(call.split("/")[-1]) > 2 else call.split("/")[0]
        if base in NOT_CALLS:
            continue
        out.append((m.start(), m.end(), call))
    return out


def likely_other_station(text: str, my_call: str = "") -> str | None:
    """Best guess for the other station's callsign: the one after DE, otherwise the first one."""
    up = " ".join(text.upper().split())
    calls = [c for _, _, c in find_callsigns(up) if c != (my_call or "").upper()]
    if not calls:
        return None
    words = up.split()
    for i, w in enumerate(words[:-1]):
        if w == "DE":
            for _, _, c in find_callsigns(words[i + 1]):
                if c != (my_call or "").upper():
                    return c
    return calls[0]
