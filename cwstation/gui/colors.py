"""Colours shared by the text stream and the waterfall.

Station 0 is the station being worked (normal text colour); the others are
stations heard on a different pitch inside the same filter (FR-RX-08).
"""
from __future__ import annotations

STATION_COLORS = ["#1b1b1b", "#1f6f4a", "#7a3fa0", "#b06000"]          # text on white
STATION_MARK_COLORS = ["#e9e9e9", "#3ddc97", "#c58cf5", "#ffb43d"]     # markers on the dark waterfall


def station_color(index: int) -> str:
    if index is None or index < 0:
        return STATION_COLORS[0]
    return STATION_COLORS[index % len(STATION_COLORS)]


def station_marker_color(index: int) -> str:
    if index is None or index < 0:
        return STATION_MARK_COLORS[0]
    return STATION_MARK_COLORS[index % len(STATION_MARK_COLORS)]
