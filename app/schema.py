"""Kanonisches Report-Schema — eine Quelle der Wahrheit.

Die Telekom-BSP-RVKU-KI-Reports haben genau diese 101 Spalten in dieser
Reihenfolge. parser, store (DB) und der Fixture-Generator leiten alles
hieraus ab, damit Schema-Aenderungen nur an einer Stelle passieren.

`RAW_COLUMNS`  = Original-Header (wie im xlsx).
`field_name()` = stabiler snake_case-Name fuer DB-Spalten / Dicts.
"""
from __future__ import annotations

import re
import unicodedata

RAW_COLUMNS: list[str] = [
    "Rahmenvertrag",
    "Kundennummer",
    "GP/Firmenname",
    "GP/Namenszusatz",
    "GP/Organisationseinheit",
    "GP/Nachname",
    "GP/Vorname",
    "GP/Straße",
    "GP/Wohnort",
    "GP/PLZ",
    "GP/Land",
    "GP/Adresszusatz",
    "Karten-/Profilnummer",
    "eID",
    "Kartentyp",
    "Rufnummer",
    "EVN",
    "Vertragsbeginn",
    "Auftragsnummer",
    "Bindefristende",
    "Bindefrist",
    "Tarif",
    "Daten Optionen",
    "Voice Optionen",
    "Mischoptionen (Voice, Data, SMS)",
    "Mehrkarten Optionen",
    "Roaming Optionen",
    "Sonstige Optionen",
    "Sperren",
    "Sperrgrund",
    "Stillegung",
    "Letzte Vertragsverlängerung",
    "VVL Grund",
    "VVL Berechtigung",
    "Data96",
    "Fax",
    "Mehrkarten Service",
    "MultiSIM-Karten-/Profilnummer 1",
    "MultiSIM-eID 1",
    "MultiSIM-Kartentyp 1",
    "MultiSIM-Karten-/Profilnummer 2",
    "MultiSIM-eID 2",
    "MultiSIM-Kartentyp 2",
    "MultiSIM-Karten-/Profilnummer 3",
    "MultiSIM-eID 3",
    "MultiSIM-Kartentyp 3",
    "MultiSIM-Karten-/Profilnummer 4",
    "MultiSIM-eID 4",
    "MultiSIM-Kartentyp 4",
    "MultiSIM-Karten-/Profilnummer 5",
    "MultiSIM-eID 5",
    "MultiSIM-Kartentyp 5",
    "MultiSIM-Karten-/Profilnummer 6",
    "MultiSIM-eID 6",
    "MultiSIM-Kartentyp 6",
    "MultiSIM-Karten-/Profilnummer 7",
    "MultiSIM-eID 7",
    "MultiSIM-Kartentyp 7",
    "MultiSIM-Karten-/Profilnummer 8",
    "MultiSIM-eID 8",
    "MultiSIM-Kartentyp 8",
    "MultiSIM-Karten-/Profilnummer 9",
    "MultiSIM-eID 9",
    "MultiSIM-Kartentyp 9",
    "MultiSIM-Karten-/Profilnummer 10",
    "MultiSIM-eID 10",
    "MultiSIM-Kartentyp 10",
    "CombiCard-/Profilnummer",
    "Rufnummer CombiCard",
    "Vertragsstatus",
    "Kündigungstermin",
    "Kündigungseingang",
    "Kundenkonto",
    "RE/Firmenname",
    "RE/Namenszusatz",
    "RE/Organisationseinheit",
    "RE/Nachname",
    "RE/Vorname",
    "RE/Straße",
    "RE/Wohnort",
    "RE/PLZ",
    "RE/Land",
    "RE/Adresszusatz",
    "Rechnungszahlart",
    "Kreditinstitut",
    "IBAN",
    "BIC",
    "Rechnungsmedium",
    "APN",
    "Kostenstelle",
    "Kostenstellennutzer",
    "EVN/Firmenname",
    "EVN/Namenszusatz",
    "EVN/Organisationseinheit",
    "EVN/Nachname",
    "EVN/Vorname",
    "EVN/Straße",
    "EVN/Wohnort",
    "EVN/PLZ",
    "EVN/Land",
    "EVN/Adresszusatz",
]


def field_name(header: str) -> str:
    """Original-Header -> stabiler snake_case-Feldname.

    'GP/Straße'                      -> 'gp_strasse'
    'MultiSIM-Karten-/Profilnummer 1'-> 'multisim_karten_profilnummer_1'
    'Mischoptionen (Voice, Data, SMS)'-> 'mischoptionen_voice_data_sms'
    """
    s = header.strip().lower()
    # Deutsche Sonderzeichen vor dem Unicode-Strip ersetzen
    s = s.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    # restliche Diakritika entfernen
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    # alles Nicht-Alphanumerische -> Unterstrich, dann zusammenfassen
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


# Reihenfolge-stabile Feldnamen (DB-Spalten / Dict-Keys)
FIELDS: list[str] = [field_name(h) for h in RAW_COLUMNS]

# Schneller Zugriff Header -> Feld und Feld -> Header
FIELD_BY_HEADER: dict[str, str] = dict(zip(RAW_COLUMNS, FIELDS))
HEADER_BY_FIELD: dict[str, str] = dict(zip(FIELDS, RAW_COLUMNS))


def normalize_header(header: str) -> str:
    """Header tolerant vergleichbar machen (Leerzeichen/Encoding-Toleranz)."""
    return field_name(header)
