#!/usr/bin/env python3
"""Sanitize-Scanner — verhindert, dass echte Telekom-BSP-Daten ins Repo gelangen.

Zweite & dritte Sicherheitsschicht (nach .gitignore). Wird von den
git-Hooks pre-commit und pre-push aufgerufen, kann aber auch manuell
oder in CI laufen:

    python scripts/sanitize_check.py --staged   # nur gestagte Änderungen (pre-commit)
    python scripts/sanitize_check.py --tracked  # alle getrackten Dateien (pre-push)

Exit 0 = sauber, Exit 1 = PII/verbotene Datei gefunden -> Hook blockt.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# --- Verbotene Dateiendungen (echte Reports / DB / Exporte) ----------------
FORBIDDEN_SUFFIXES = {".xlsx", ".xls", ".db", ".sqlite", ".sqlite3", ".csv"}

# --- PII-Muster ------------------------------------------------------------
# Jede Regel: (Name, kompiliertes Pattern). Treffer => Leak-Verdacht.
PII_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # Deutsche IBAN: DE + 20 Ziffern, optional in 4er-Gruppen mit Leerzeichen
    ("IBAN", re.compile(r"\bDE\d{2}[ ]?(?:\d{4}[ ]?){4}\d{2}\b")),
    # BIC (deutsche Banken): 4 Buchstaben + DE + 2 + optional 3
    ("BIC", re.compile(r"\b[A-Z]{4}DE[A-Z0-9]{2}(?:[A-Z0-9]{3})?\b")),
    # Deutsche Mobilfunknummer: +49/0049/0 gefolgt von 15x/16x/17x + Rest
    ("Rufnummer", re.compile(r"\b(?:\+49|0049|0)1[5-7]\d[ /-]?\d{6,8}\b")),
]

# Dateien/Pfade, die der Scanner selbst nicht als Leak werten soll.
# (Dieses Skript enthält die Muster als Regex, nicht als echte Werte.)
SELF_ALLOW = {"scripts/sanitize_check.py"}

# Nur Textdateien inhaltlich scannen; Binärdateien werden über die
# Endungsregel ohnehin geblockt.
TEXT_SUFFIXES = {
    ".py", ".js", ".ts", ".html", ".css", ".json", ".md", ".txt",
    ".yml", ".yaml", ".toml", ".cfg", ".ini", ".sh", ".env", "",
}


def _git(args: list[str]) -> list[str]:
    out = subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True
    ).stdout
    return [line for line in out.splitlines() if line.strip()]


def _staged_files() -> list[str]:
    return _git(["diff", "--cached", "--name-only", "--diff-filter=ACM"])


def _tracked_files() -> list[str]:
    return _git(["ls-files"])


def _mask(text: str) -> str:
    """Treffer maskieren, damit der Scanner-Output selbst keine PII zeigt."""
    if len(text) <= 4:
        return "*" * len(text)
    return text[:2] + "*" * (len(text) - 4) + text[-2:]


def scan_paths(paths: list[str]) -> list[str]:
    problems: list[str] = []
    for rel in paths:
        if rel in SELF_ALLOW:
            continue
        p = Path(rel)
        suffix = p.suffix.lower()

        if suffix in FORBIDDEN_SUFFIXES:
            problems.append(f"VERBOTENE DATEI: {rel} ({suffix})")
            continue

        if suffix not in TEXT_SUFFIXES:
            continue
        if not p.exists():
            continue

        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        for lineno, line in enumerate(content.splitlines(), start=1):
            for name, pattern in PII_PATTERNS:
                for m in pattern.finditer(line):
                    problems.append(
                        f"PII-VERDACHT [{name}]: {rel}:{lineno} -> {_mask(m.group())}"
                    )
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--staged", action="store_true", help="nur gestagte Dateien (pre-commit)")
    g.add_argument("--tracked", action="store_true", help="alle getrackten Dateien (pre-push)")
    args = ap.parse_args()

    paths = _staged_files() if args.staged else _tracked_files()
    problems = scan_paths(paths)

    if problems:
        print("\n  SANITIZE-CHECK FEHLGESCHLAGEN — Push/Commit blockiert:\n", file=sys.stderr)
        for prob in problems:
            print(f"   - {prob}", file=sys.stderr)
        print(
            "\n  Echte Telekom-Daten gehoeren NUR nach data/ (gitignored).\n"
            "  Datei entfernen: git rm --cached <datei>\n",
            file=sys.stderr,
        )
        return 1

    print("sanitize-check: sauber")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
