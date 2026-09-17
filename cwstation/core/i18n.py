"""User-interface strings from JSON language files (NFR-08).

Add a language by copying cwstation/i18n/en.json to e.g. es.json and
translating the values. Missing keys fall back to English, then to the key.
"""
from __future__ import annotations

import json
from pathlib import Path

from .resources import resource_path

_strings: dict[str, str] = {}
_fallback: dict[str, str] = {}


def available_languages() -> list[str]:
    folder = resource_path("cwstation/i18n")
    return sorted(p.stem for p in Path(folder).glob("*.json"))


def load(lang: str = "en") -> None:
    global _strings, _fallback
    folder = Path(resource_path("cwstation/i18n"))
    _fallback = json.loads((folder / "en.json").read_text(encoding="utf-8"))
    path = folder / f"{lang}.json"
    _strings = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def tr(key: str, **kw) -> str:
    s = _strings.get(key) or _fallback.get(key) or key
    try:
        return s.format(**kw) if kw else s
    except (KeyError, IndexError):
        return s
