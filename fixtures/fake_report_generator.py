"""Erzeugt synthetische RVKU-KI-Reports (xlsx) mit identischer Struktur.

NUR Fantasiewerte (faker) — niemals echte Daten. Dient Tests und lokaler
Entwicklung. Struktur (101 Spalten, Sheet 'Kundennummer', datetime-Datumsfelder)
spiegelt die echten Reports, wie in der Analyse festgestellt.

CLI:
    python fixtures/fake_report_generator.py out.xlsx --rows 50 --seed 1
"""
from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

from faker import Faker
from openpyxl import Workbook

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import schema  # noqa: E402

SHEET = "Kundennummer"

TARIFE = [
    "Business Mobil L mit Top-Handy 3Gen",
    "BusinessFlex Mobil S",
    "Business Mobil M mit Premium-Hd3Gen",
    "Business Mobil XL",
]
KARTENTYPEN = ["TRIPLE-SIM 1,8V", "eSIM Profil", "Nano-SIM (4FF)"]
DATEN_OPT = ["Daten-Flat 5GB", "Daten-Flat 10GB", "Daten-Flat unlimited", "-"]
VOICE_OPT = ["AllNet-Flat", "Voice-Flat", "Minutenpaket 100", "Minutenpaket 500", "-"]
ROAMING_OPT = ["EU-Roaming", "World-Roaming", "Travel & Surf", "-"]
VVL_BER = ["berechtigt", "nicht berechtigt"]


def _iban(fake: Faker) -> str:
    return fake.iban()


def generate_rows(fake: Faker, n: int, base_date: dt.datetime,
                  rahmenvertrag: str | None = None) -> list[dict]:
    rows = []
    for i in range(n):
        firma = fake.company()
        vertragsbeginn = base_date - dt.timedelta(days=fake.random_int(30, 4000))
        bindefrist_monate = fake.random_element([12, 24, 36])
        bindefristende = vertragsbeginn + dt.timedelta(days=bindefrist_monate * 30)
        kartentyp = fake.random_element(KARTENTYPEN)
        row = {f: None for f in schema.FIELDS}
        row.update(
            {
                "rahmenvertrag": rahmenvertrag or fake.bothify("RV-#####"),
                "kundennummer": "100" + fake.numerify("######"),
                "gp_firmenname": firma,
                "gp_organisationseinheit": fake.bs().title(),
                "gp_strasse": fake.street_address(),
                "gp_wohnort": fake.city(),
                "gp_plz": fake.postcode(),
                "gp_land": "DE",
                "karten_profilnummer": fake.numerify("8965#########"),
                "eid": fake.numerify("8949########0####") if kartentyp == "TRIPLE-SIM 1,8V" else None,
                "kartentyp": kartentyp,
                "rufnummer": "0151" + fake.numerify("########"),
                "evn": fake.random_element(["Ja", "Nein"]),
                "vertragsbeginn": vertragsbeginn,
                "auftragsnummer": fake.numerify("9########"),
                "bindefristende": bindefristende,
                "bindefrist": str(bindefrist_monate),
                "tarif": fake.random_element(TARIFE),
                "daten_optionen": fake.random_element(DATEN_OPT),
                "voice_optionen": fake.random_element(VOICE_OPT),
                "roaming_optionen": fake.random_element(ROAMING_OPT),
                "sperren": None if fake.random_int(0, 20) else "Dienste3.Anbieter",
                "letzte_vertragsverlaengerung": vertragsbeginn + dt.timedelta(days=365),
                "vvl_berechtigung": fake.random_element(VVL_BER),
                "vertragsstatus": "A",
                "kundenkonto": fake.numerify("########"),
                "re_firmenname": firma,
                "re_strasse": fake.street_address(),
                "re_wohnort": fake.city(),
                "re_plz": fake.postcode(),
                "re_land": "DE",
                "rechnungszahlart": "Lastschrift",
                "kreditinstitut": fake.company() + " Bank",
                "iban": _iban(fake),
                "bic": fake.swift8(),
                "rechnungsmedium": "elektronisch",
                "kostenstelle": fake.bothify("KST-####-??"),
                "kostenstellennutzer": fake.name(),
            }
        )
        # ~Hälfte mit MultiSIM (1, manche 2)
        if fake.random_int(0, 1):
            row["multisim_karten_profilnummer_1"] = fake.numerify("8965#########")
            row["multisim_eid_1"] = fake.numerify("8949########0####")
            row["multisim_kartentyp_1"] = "TRIPLE-SIM 1,8V"
            if fake.random_int(0, 1):
                row["multisim_karten_profilnummer_2"] = fake.numerify("8965#########")
                row["multisim_kartentyp_2"] = "eSIM Profil"
        rows.append(row)
    return rows


def generate_report(
    path: str | Path, rows: int = 50, seed: int = 0,
    report_date: dt.datetime | None = None, rahmenvertrag: str | None = None
) -> Path:
    fake = Faker("de_DE")
    Faker.seed(seed)
    base = report_date or dt.datetime(2026, 6, 25, 8, 43, 49)

    wb = Workbook()
    ws = wb.active
    ws.title = SHEET
    ws.append(schema.RAW_COLUMNS)
    for row in generate_rows(fake, rows, base, rahmenvertrag):
        ws.append([row[f] for f in schema.FIELDS])

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("out")
    ap.add_argument("--rows", type=int, default=50)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    p = generate_report(args.out, rows=args.rows, seed=args.seed)
    print(f"geschrieben: {p} ({args.rows} Zeilen, synthetisch)")


if __name__ == "__main__":
    main()
