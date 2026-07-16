# Redesign: Controlling-Cockpit (3 Bereiche)

Ergebnis des Multi-Perspektiven-Design-Reviews (wf_3bee2a51). Vom Ein-Seiten-
Bestandsviewer zum Data-Dense-Controlling-Cockpit. Trennung Report/Rechnung bleibt;
Rufnummer = Brücke, Vormonatsvergleich = roter Faden.

## Navigation
Persistente Top-Nav mit 3 Bereichen + Hash-Routing (`#/vertraege`, `#/rechnungen`,
`#/rechnungen/<id>`, `#/controlling`). Globaler Scope (Rahmenvertrag) über alle Bereiche.
Rufnummer überall klickbarer Anker (Vertrag ↔ Rechnungsposition). Globale Actions in
Topbar: Suche, Laden, Netto/Brutto, Einstellungen (nur noch Verwaltung), Abmelden.

## Bereich 1 — Verträge (Report/Stammdaten, verschlankt)
- Redundanzen auflösen (Gesperrt/Bindefrist einmal, aktionsorientiert).
- Doughnuts → horizontale Balken mit Wert-Labels; Options-Charts gebündelt.
- VVL-Arbeitsliste mit Monatskosten, Rabatt, kumulierter „at risk"-Summe; Filter
  „VVL-berechtigt UND auslaufend"; CSV.
- Drawer: Rufnummer-Sprung zu Rechnungspositionen; Datenauslastung (Ampel ≥90%).
- Maßnahmen-Status je Vertrag (Enum: geprüft/VVL beauftragt/kündigen/Rücksprache).

## Bereich 2 — Rechnungen (Kernwunsch, kein Modal)
- **Übersicht/Selektor**: Nr., Zeitraum, Ausstellung/Fällig (Ampel), echtes
  Netto/USt/Brutto, #Positionen, #Rufnummern, Δ-Netto Vormonat, Reconciliation-Status.
- **Einzelrechnung**: Kopf (Nr., Kundenkonto, Zeitraum, Fälligkeit, Summen) +
  Reconciliation-Badge (zugeordnet/Rest) + Δ-Kachel Vormonat. Panels: je Kostenstelle
  (Δ), je Kategorie (Anteil %), Top-Kostentreiber, Auffälligkeiten
  (Verbrauch/Roaming, größte Deltas, neu/weggefallen/geändert), Datenauslastung
  aggregiert, auslaufende Rabatte (mindestlaufzeit_ende) mit Kostenimpact.
  Positionsliste mit Kategorie-Spalte, druck-/CSV-fähig.

## Bereich 3 — Controlling (aus Modals befördert)
Kosten-KPIs (Netto Monat +Δ%, Ø/aktive SIM, Rabattsumme+quote, Zuordnung X/N),
Kostentrend (Linie), Top-Kostenstellen (Pareto, horiz. Balken), Kostenkomposition
(gestapelt: grundpreis+option−rabatt+verbrauch=netto). Bezugszeitraum immer beschriften.

## Kostendarstellung
- Netto default. **Globalen 1.19-Faktor abschaffen** → echte total_net/total_tax/
  total_gross je Rechnung; Netto/Brutto rechnet mit realem gross/net, Brutto nur auf
  Summenebene.
- Nie nackter Wert → immer Wert + Δ (€ und %).
- Kosten-Summen mit Abdeckungsgrad; nicht gematchte Kosten als Reconciliation-Bucket
  sichtbar (nicht still None).

## Visual-System
- Design-Tokens (Radius, Spacing, Typo/Zahlenskala).
- Magenta #e20074 nur Marken-/Fokus-Akzent; KPI-Zahlen neutral (--ink); Datenbalken/
  -linien neutraler Ton (Slate), Magenta nur für Selektion.
- Semantik Rot/Amber/Grün für Ampeln/Δ. Kleiner Text: --magenta-dark (WCAG-AA).
- Emojis → inline-SVG-Icons (Heroicons/Lucide, currentColor, keine CDN wegen CSP).
- tabular-nums global, rechtsbündige Zahlenspalten; dichtere Zeilen, Zebra;
  Chart-Titel als HTML statt Canvas.

## Backend-Erweiterungen
- `analytics.invoice_diff(old, new)` — Δ netto je rufnummer/kostenstelle/kategorie
  + Listen neu/weggefallen/geändert.
- `analytics.reconcile(lines, total_net)` — Summe je Rufnummer vs. total, Rest-Bucket.
- `analytics.datenauslastung(lines)` — aggregiert vereinbart vs. verbraucht,
  Über-/Unterversorgungslisten.
- `analytics.rabatt_auslauf(...)` / expiring um Kostenfelder erweitern.
- API: `/api/costs/*` mit invoice_id-Parameter; `/api/invoices/{id}` Detail
  (Kopf + Aggregate + Diff vs. Vorrechnung); kosten_je_kategorie + Auslastung exponieren.

## Weglassen
Globaler 1.19-Faktor; Kosten-/Verlauf-Modals; Rechnungsliste in Einstellungen als
einziger Zugang; alle Emoji-Icons; redundante Bestands-KPIs; 3 separate Options-Charts;
Doughnuts bei ~3 Werten; Magenta als Datenfläche; stilles None bei nicht gematchten Kosten.

## Bewusst NICHT jetzt (YAGNI)
Budget/Plan-Ist (Soll-Ist, Run-Rate, Ampel) — braucht neues Budget-Datenmodell, separat.

## Build-Reihenfolge
1. Nav-Gerüst + Hash-Routing; Modals → Seiten; Einstellungen verschlanken.
2. Rechnungsübersicht + Einzelrechnung (echte Summen, Positionen, druck/CSV).
3. `invoice_diff` + Vormonats-Δ prominent.
4. `reconcile` + Zuordnungs-KPI + unmatched-Filter.
5. Kosten-KPI-Cockpit (Δ-Badges, Trend, Top-Kostenstellen).
6. Visual-Pass (Tokens, Entfärbung, SVG-Icons, A11y, tabular-nums).
7. Brachliegende Analytik ausliefern (kosten_je_kategorie, Datenauslastung).
8. VVL-Arbeitsliste mit Kosten/at-risk + Overage + auslaufende Rabatte; Maßnahmen-Status.
