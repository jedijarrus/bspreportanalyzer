"""Pytest-Fixtures. Synthetische Reports werden zur Laufzeit erzeugt —
niemals als xlsx im Repo (data/Scanner würde sie blocken)."""
import datetime as dt
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fixtures.fake_report_generator import generate_report  # noqa: E402
from fixtures.fake_invoice_csv_generator import generate_invoice_csv  # noqa: E402


@pytest.fixture
def make_report(tmp_path):
    """Factory: erzeugt eine synthetische Report-xlsx und gibt den Pfad zurück."""
    def _make(rows=20, seed=0, report_date=dt.datetime(2026, 6, 25, 8, 43, 49),
              name=None):
        fname = name or f"{report_date:%Y%m%d-%H%M%S}_RVKU-KI_000001_0000000000.xlsx"
        path = tmp_path / fname
        generate_report(path, rows=rows, seed=seed, report_date=report_date)
        return path
    return _make


@pytest.fixture
def make_invoice_csv(tmp_path):
    """Factory: synthetische Rechnungs-CSV (Telekom-Positions-Format)."""
    def _make(rufnummern=None, n=5, seed=0, invoice_number="230000000001",
              period=None, issue_date=None, name=None):
        fname = name or f"Rechnung_{invoice_number}.csv"
        path = tmp_path / fname
        extra = {}
        if period is not None:
            extra["period"] = period
        if issue_date is not None:
            extra["issue_date"] = issue_date
        generate_invoice_csv(path, rufnummern=rufnummern, n=n, seed=seed,
                             invoice_number=invoice_number, **extra)
        return path
    return _make
