"""Build-Marker: liest die beim Docker-Build erzeugten Dateien BUILD_SHA/BUILD_TIME.

Damit lässt sich im Log, per /api/version und im Login-Screen sofort erkennen, ob
der laufende Container den aktuellen Code fährt (statt eines gecachten alten Images).
Lokal ohne Build sind die Werte „dev".
"""
from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _read(name: str) -> str:
    try:
        return (_ROOT / name).read_text(encoding="utf-8").strip() or "dev"
    except OSError:
        return "dev"


def build_info() -> dict[str, str]:
    return {"sha": _read("BUILD_SHA"), "built": _read("BUILD_TIME")}
