"""Locate bundled resources both in a source checkout and in a PyInstaller build."""
from __future__ import annotations

import sys
from pathlib import Path


def base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]  # repository/app root


def resource_path(relative: str) -> Path:
    return base_dir() / relative


def model_dir() -> Path:
    """DeepCW model folder: bundled 'models/deepcw-engine', else ../third_party/deepcw-engine."""
    candidates = [
        base_dir() / "models" / "deepcw-engine",
        base_dir().parent / "third_party" / "deepcw-engine",
        base_dir() / "third_party" / "deepcw-engine",
    ]
    for c in candidates:
        if (c / "model.onnx").exists():
            return c
    return candidates[0]
