#!/usr/bin/env python3
"""Vertaa tulkintoja viitetekstiin: merkkivirhe (CER) ja sanavirhe (WER).

Käyttö:
  python compare.py viite.txt deepcw.txt morse_expert.txt

Tiedostoissa voi olla vapaata tekstiä. rx_live.py:n --log-tiedostosta
(aikaleima<TAB>RX<TAB>teksti) käytetään vain tekstisarake. Vertailu tehdään
isoilla kirjaimilla ja välilyönnit yhdistäen.

Lisenssi: AGPL-3.0-or-later.
"""
from __future__ import annotations

import sys
from pathlib import Path


def load(path: Path) -> str:
    words = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split("\t")
        text = parts[2] if len(parts) >= 3 and parts[1] == "RX" else line
        words.append(text)
    return " ".join(" ".join(words).upper().split())


def edit_distance(a, b) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    ref = load(Path(sys.argv[1]))
    print(f"Viite: {len(ref)} merkkiä, {len(ref.split())} sanaa\n")
    print(f"{'tiedosto':30s} {'CER':>7s} {'CER ilman välejä':>17s} {'WER':>7s}")
    for p in sys.argv[2:]:
        hyp = load(Path(p))
        cer = edit_distance(ref, hyp) / max(1, len(ref))
        cer_ns = edit_distance(ref.replace(" ", ""), hyp.replace(" ", "")) / max(1, len(ref.replace(" ", "")))
        wer = edit_distance(ref.split(), hyp.split()) / max(1, len(ref.split()))
        print(f"{Path(p).name:30s} {100*cer:6.1f}% {100*cer_ns:16.1f}% {100*wer:6.1f}%")


if __name__ == "__main__":
    main()
