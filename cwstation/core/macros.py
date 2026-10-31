"""Macro text expansion and CW text sanitising."""
from __future__ import annotations

import re

# Characters the keyer firmware (PROTOCOL.md v1) can send.
CW_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.,?/=+-()\"':;@! <>")

MORSE = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.", "G": "--.", "H": "....",
    "I": "..", "J": ".---", "K": "-.-", "L": ".-..", "M": "--", "N": "-.", "O": "---", "P": ".--.",
    "Q": "--.-", "R": ".-.", "S": "...", "T": "-", "U": "..-", "V": "...-", "W": ".--", "X": "-..-",
    "Y": "-.--", "Z": "--..", "0": "-----", "1": ".----", "2": "..---", "3": "...--", "4": "....-",
    "5": ".....", "6": "-....", "7": "--...", "8": "---..", "9": "----.", ".": ".-.-.-", ",": "--..--",
    "?": "..--..", "/": "-..-.", "=": "-...-", "+": ".-.-.", "-": "-....-", "(": "-.--.", ")": "-.--.-",
    '"': ".-..-.", "'": ".----.", ":": "---...", ";": "-.-.-.", "@": ".--.-.", "!": "-.-.--",
}


def airtime_s(text: str, wpm: float) -> float:
    """Seconds the keyer needs to send sanitised `text` at `wpm`.

    Same PARIS timing as the firmware and keyer_sim: dit 1, dah 3, element gap 1, character gap 3,
    word gap 7 units, unit = 1.2 / WPM s; letters inside <..> (prosigns) have no character gap.
    Weight does not change the total. "PARIS " = 50 units = 3.0 s at 20 WPM.
    """
    units, prosign = 0, False
    for ch in text:
        if ch == "<":
            prosign = True
        elif ch == ">":
            prosign = False
            units += 2
        elif ch == " ":
            units += 4
        elif ch in MORSE:
            code = MORSE[ch]
            units += sum(1 if s == "." else 3 for s in code) + len(code) + (0 if prosign else 2)
    return units * 1.2 / max(1.0, float(wpm))


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
