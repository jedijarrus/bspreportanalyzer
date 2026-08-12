"""Tests für app.employee_parser — Erkennung + Parsen der Mitarbeiterliste (xlsx)."""
import openpyxl

from app import employee_parser


def _emp_xlsx(tmp_path, rows, header=("PersNr", "Nachname", "Vorname"), name="Mitarbeiter.xlsx"):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(list(header))
    for r in rows:
        ws.append(list(r))
    p = tmp_path / name
    wb.save(p)
    return p


def test_erkennt_mitarbeiter_workbook(tmp_path):
    p = _emp_xlsx(tmp_path, [(1234, "Mustermann", "Martin")])
    assert employee_parser.is_employee_workbook(p) is True


def test_report_ist_kein_mitarbeiter_workbook(tmp_path):
    # Report-artige Kopfzeile ohne PersNr -> nicht als Mitarbeiterliste erkannt
    p = _emp_xlsx(tmp_path, [(1, "x", "y")], header=("Rufnummer", "Tarif", "Status"))
    assert employee_parser.is_employee_workbook(p) is False


def test_parse_employees_normalisiert(tmp_path):
    p = _emp_xlsx(tmp_path, [(1234, "Mustermann", "Martin"), (None, None, None), (56, "Meier", "Anna")])
    emps = employee_parser.parse_employees(p)
    assert {e["persnr"] for e in emps} == {"1234", "56"}   # Leerzeile raus, PersNr als String ohne '.0'
    e = next(x for x in emps if x["persnr"] == "1234")
    assert e["nachname"] == "Mustermann" and e["vorname"] == "Martin"
