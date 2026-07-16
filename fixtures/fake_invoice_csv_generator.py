"""Erzeugt synthetische Telekom-Rechnungs-CSV (positionelles Format, cp1252, ';').

Nur Fantasiewerte. Bildet die reale Struktur ab (siehe Analyse): eine Kopfzeile
(34 Spalten) + Detailzeilen (22 Spalten) je Rufnummer. Anders als die XML tragen
hier ALLE Zeilen — auch Datenverbrauch — die Rufnummer (Spalte 5), daher ist
Auslastung pro Vertrag möglich.

Spalten der Detailzeile (0-indiziert):
  0 Rechnungsnr | 1 Ausstelldatum | 2 Karten-/Profilnr | 3 Kostenstelle |
  4 Kostenstellennutzer | 5 Rufnummer | 6 "Telefonie" | 7 Id | 8 Gruppe |
  9 Id | 10 Leistung/Label | 12 Wert (Datenvolumen) | 13 Einheit |
  14 Zeitraum-Start | 15 Zeitraum-Ende | 16 USt% | 17 Betrag
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from faker import Faker

N_COLS = 22


def _row(**kw) -> list[str]:
    r = [""] * N_COLS
    for i, v in kw.items():
        r[int(i)] = "" if v is None else str(v)
    return r


def generate_invoice_csv(
    path, rufnummern=None, n=5, seed=0, rahmenvertrag="RV-DEMO",
    invoice_number="230000000001", issue_date="06.07.2026", due_date="20.07.2026",
    period=("01.06.2026", "30.06.2026"), kundenkonto="0099999999",
) -> Path:
    fake = Faker("de_DE")
    Faker.seed(seed)
    if rufnummern is None:
        rufnummern = ["0151" + fake.numerify("########") for _ in range(n)]

    out: list[list[str]] = []
    # Kopfzeile (34 Spalten) — invoice-level
    head = [""] * 34
    head[0], head[1], head[2], head[3] = invoice_number, issue_date, rahmenvertrag, "Rechnung"
    head[5], head[6], head[7] = kundenkonto, period[0], period[1]
    head[11] = due_date
    head[32], head[33] = "19,00", "EUR"
    out.append(head)

    def eur(x):  # deutsches Dezimalformat
        return f"{x:.2f}".replace(".", ",")

    for i, ruf in enumerate(rufnummern):
        base = dict(**{"0": invoice_number, "1": issue_date,
                       "2": "8949" + fake.numerify("################"),
                       "3": f"KST-{fake.random_int(1000, 9999)}", "4": fake.name(),
                       "5": ruf, "6": "Telefonie"})
        grund = round(59.95 + (i % 5) * 5, 2)
        # Grundpreis
        out.append(_row(**base, **{"8": "Grundpreise", "10": "Business Mobil L mit Top-Handy (3. Generation)",
                                   "14": period[0], "15": period[1], "16": "19", "17": eur(grund)}))
        # Rabatt
        out.append(_row(**base, **{"8": "Rahmenvertragsrabatte / Guthaben",
                                   "10": "25% auf Grundpreis Business Mobil L", "14": period[0],
                                   "15": period[1], "16": "19", "17": eur(-round(grund * 0.25, 2))}))
        # Option
        out.append(_row(**base, **{"8": "Grundpreise", "10": "DataPlus 12 GB",
                                   "14": period[0], "15": period[1], "16": "19", "17": eur(16.76)}))
        # Datenvolumen: vereinbart + insgesamt verbraucht (in KB) — MIT Rufnummer
        out.append(_row(**base, **{"8": "Info zu Ihrem Datenvolumen des Abrechnungsmonats im Inland:",
                                   "10": "Vertraglich vereinbartes Datenvolumen:", "12": "83886080", "13": "KB"}))
        used_kb = 8388608 + i * 500000  # ~8 GB aufwärts
        out.append(_row(**base, **{"8": "Info zu Ihrem Datenvolumen des Abrechnungsmonats im Inland:",
                                   "10": "Insgesamt verbrauchtes Datenvolumen:", "12": str(used_kb), "13": "KB"}))

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="cp1252", newline="") as f:
        csv.writer(f, delimiter=";").writerows(out)
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("out")
    ap.add_argument("--lines", type=int, default=5)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    p = generate_invoice_csv(args.out, n=args.lines, seed=args.seed)
    print(f"geschrieben: {p} (synthetisch)")


if __name__ == "__main__":
    main()
