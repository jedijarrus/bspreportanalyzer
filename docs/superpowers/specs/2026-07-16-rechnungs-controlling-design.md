# Rechnungs-/Kostenanalyse (Controlling) — Design

Erweiterung des BSP Report Analyzers um Rechnungsimport und Kostenauswertung.
Voll integriert in die bestehende Flottensicht (Join über Rufnummer).

## Kontext / Datenquelle

- Format: **UBL 2.1 / XRechnung 3.0** (EN16931, Peppol BIS Billing 3.0), `ubl:Invoice`.
- Monatsrechnung je Kundenkonto. Beispiel: 1291 `InvoiceLine`, 192 Rufnummern
  (= dieselbe Flotte wie im großen BSP-Report), ~12.5k € netto.
- Je `InvoiceLine`: `LineExtensionAmount`, `InvoicedQuantity`, `Price/PriceAmount`,
  `Item/Name` (Leistungsart), `InvoicePeriod`, und `AdditionalItemProperty`
  (Name/Value): **Rufnummer, Kostenstelle, Kostenstellennutzer**, Vertragsbeginn,
  Kündigungsfrist, Mindestlaufzeit-Ende, Datenvolumen vereinbart/verbraucht (+Einheit).

### Kritische Parser-Erkenntnisse (validiert an Echtdaten)
- **Nur Ladungen (+) tragen Rufnummer/Kostenstelle** (523/530). Rabatte (−370)
  und Info-Zeilen (391) tragen **keine** → müssen zugeordnet werden.
- **Rufnummer-Carry-Forward in Dokumentreihenfolge** (Rabatt/Info erbt die zuletzt
  gesehene Rufnummer) rekonstruiert Kosten je Vertrag: 192 Rufnummern, Summe =
  Rechnungs-Netto (Rest −34 € vor erster Rufnummer → Bucket „nicht zugeordnet").
- Datenauslastung (verbraucht/vereinbart) belastbar (gleiche Einheit); absolute
  Einheit (KB/MB/GB) muss aus `Dateneinheit` normiert werden.

## Datenmodell (SQLite, neben reports/contracts)

- `invoices`: id, invoice_number, kundenkonto, issue_date, due_date,
  period_start, period_end, filename, imported_at, total_net, total_tax, total_gross.
- `invoice_lines`: id, invoice_id FK (CASCADE), rufnummer, kostenstelle,
  kostenstellennutzer, item_name, category, amount, quantity, price,
  period_start, period_end, data_contracted_gb, data_used_gb.
  - `category` ∈ {grundpreis, option, rabatt, verbrauch, info} (aus Item/Name klassifiziert).
  - Indizes auf rufnummer, kostenstelle, invoice_id.

## Komponenten

- `app/invoice_parser.py` — XML → Kopf + normalisierte Positionen (Carry-Forward,
  Kategorisierung, Einheiten-Normierung). Rein, testbar.
- `app/store.py` — add_invoice / list_invoices / delete_invoice / invoice_lines /
  all_invoice_lines (mit Kopf-Meta für Trend).
- `app/analytics.py` — kosten_je_rufnummer, kosten_je_kostenstelle,
  kosten_je_kategorie, rabatt_je_vertrag (Grundpreis vs. effektiv),
  kosten_trend (über invoice period), datenauslastung.
- `app/api.py` — /api/invoices (POST/GET/DELETE), Kosten in /api/current je
  Rufnummer anreichern, /api/costs/kostenstellen, /api/costs/trend.
- `web/` — Integration siehe unten.
- `fixtures/fake_invoice_generator.py` — synthetische XRechnung-XML (Tests).

## Auswertungen (Prioritäten)

1. **Kosten je Kostenstelle/Vertrag** — Summe aktueller Monat je Kostenstelle
   (+ Vertragsanzahl) und je Rufnummer (netto: Grundpreis, Rabatt, effektiv).
2. **Kostentrend über Monate** — Linie gesamt + je Kostenstelle (mehrere Rechnungen).
3. **Rabatt-/Grundpreis-Transparenz** — je Vertrag Grundpreis vs. effektiv,
   Rabattsumme, auslaufende Rabatte (Mindestlaufzeit-Ende).

## Integration ins Dashboard

- Vertrags-Tabelle: Spalten **Monatskosten**, **Rabatt** (sortierbar); Facetten
  Kosten-Bucket, „hat Rabatt".
- Detail-Drawer: Abschnitt **Kosten (Monat)** — Positionen der Rufnummer
  (Leistung, Kategorie, Betrag) + Netto + Rabatt + Datenauslastung.
- Neue Ansichten (wie „Verlauf"): **Kostenstellen** und **Kostentrend**.
- **Netto/Brutto-Umschalter** im Dashboard (beide Sichten).
- Upload „Rechnung laden" (.xml) neben „Report laden" (.xlsx); Rechnungen-Liste in
  Einstellungen. CSV-Export um Kostenfelder erweitert.

## Sicherheit

- Echte Rechnungen sind PII (Rufnummern, Adressen, Beträge). `*.xml` + `Rechnung/`
  in `.gitignore`, `.xml` in `sanitize_check` FORBIDDEN_SUFFIXES (erledigt).
  Rechnungen liegen nur unter `data/` (Volume). Tests gegen synthetische XML.

## Matching Rechnung ↔ Vertrag

- Join über **Rufnummer** (Primärschlüssel im Analyzer). Kosten der neuesten
  Rechnung reichern die aktuelle Flottensicht an. Rufnummern ohne Vertrag (oder
  umgekehrt) werden best-effort angezeigt/geflaggt.
