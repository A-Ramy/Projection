"""Hand-built sheet for the metrics engine, with answers that can be worked out by hand. Today = Oct 14, 2026.

COSTS (month totals, Jan–Sep complete; Oct in progress):
    PPC A        5,000/mo Q1, 6,000/mo Q2, 10,000/mo Q3   (best quarter 30,000)
    SEO B        1,000/mo Q3
    Mailer C     2,000 in Aug, a $0 row in Sep (no leads)  -> "Other marketing (unprojected)" in Q3
    ACQ Payroll  20,000/mo Jan–Sep                         (non-marketing)
REVENUES (Q3 total 415,000, 24 deals):
    PPC A    20 deals: 14 Wholesale × 15,000, 4 Novation × 25,000, F&F 40,000 and −5,000  (Aug/Sep)
    SEO B    Wholesale 12,000 (Sep 3)
    SELF GEN Wholesale 20,000 (Aug 1), Retail Listing 8,000 (Sep 1)
    Inbound X Fix & Flip 30,000 (Jul 15)
    + PPC A Wholesale: 3 × 9,000 in Feb, 5 × 10,000 in May, 18,000 on Oct 5
KPIs:
    PPC A Q3: 200 leads created Jul (60) / Aug (70) / Sep (70); per 10: 4 Qualified (+1 day), 5 Disqualified
              (+2 days), 1 Pending (blank Date). Leads 0–19 have the addresses of the 20 Q3 deals.
              Funnel: leads 0–9 Appointment Set Jul 20, 0–5 Appointment Held Jul 25, 6–7 "No-Show" Jul 26,
              0–2 Closed Deal Aug 10.
    PPC A Q2: 100 leads created May, 3 per 10 Qualified.
    SEO B:    10 leads created Aug (4 Qualified) + 1 created Jun 30, Qualified Jul 2.
    Before start: a Pending lead created Dec 20, 2025, and a Lead created Dec 20, 2025, Qualified Jan 5, 2026.
ACQ reps: even leads / first 12 PPC A Q3 deals = Rep A, odd / the rest = Rep B.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from projection.sheets import RawSheet
from tests.fixtures import serial

TODAY = date(2026, 10, 14)
LINK = "https://app.gohighlevel.com/v2/location/L/contacts/detail/{}"


def _s(d: datetime) -> float:
    return serial(d.year, d.month, d.day, d.hour, d.minute)


def _month_end(y: int, m: int) -> float:
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return _s(datetime.combine(nxt - timedelta(days=1), datetime.min.time()))


def _costs() -> list[list]:
    rows = [["Date", "Source", "Cost"]]
    for m in range(1, 10):
        rows.append([])  # separator
        rows.append([_month_end(2026, m), "PPC A", 5000 if m <= 3 else 6000 if m <= 6 else 10000])
        rows.append([_month_end(2026, m), "ACQ Payroll", 20000])
        if m >= 7:
            rows.append([_month_end(2026, m), "SEO B", 1000])
        if m in (8, 9):  # Sep: $0 posted, so September's costs count as complete
            rows.append([_month_end(2026, m), "Mailer C", 2000 if m == 8 else 0])
    return rows


def _rev(d: datetime, addr: str, src: str, amount: float, exit_: str, acq: str = "") -> list:
    return [_s(d), addr, src, amount, exit_, "", "", acq, "", ""]


def _revenues() -> list[list]:
    rows = [["Date Closed", "Address", "Source", "Revenue", "Exit Strategy", "AGENT", "FUS", "ACQ", "DISPO",
             "DISPO LM"]]
    for j in range(20):
        exit_, amount = ("Wholesale", 15000) if j < 14 else ("Novation", 25000) if j < 18 else (
            "Fix & Flip", 40000 if j == 18 else -5000)
        d = datetime(2026, 8 if j < 10 else 9, 10 + j % 10)
        rows.append(_rev(d, f"{j} Main St", "PPC A", amount, exit_, "Rep A" if j < 12 else "Rep B"))
    rows += [
        _rev(datetime(2026, 9, 3), "1 Seo Way", "SEO B", 12000, "Wholesale"),
        _rev(datetime(2026, 8, 1), "1 Self Rd", "SELF GEN", 20000, "Wholesale"),
        _rev(datetime(2026, 9, 1), "2 Self Rd", "SELF GEN", 8000, "Retail Listing"),
        _rev(datetime(2026, 7, 15), "1 Inbound Ave", "Inbound X", 30000, "Fix & Flip"),
        *[_rev(datetime(2026, 2, 10 + i), f"{i} Feb St", "PPC A", 9000, "Wholesale") for i in range(3)],
        *[_rev(datetime(2026, 5, 10 + i), f"{i} May St", "PPC A", 10000, "Wholesale") for i in range(5)],
        _rev(datetime(2026, 10, 5), "1 Oct St", "PPC A", 18000, "Wholesale"),
    ]
    return rows


def _kpi(date_: datetime | None, created: datetime, kpi: str, quality: str, src: str, acq: str = "",
         addr: str = "") -> list:
    return [_s(date_) if date_ else "", _s(created), kpi, quality, "", acq, src, "", "", addr]


def _kpis() -> tuple[list[list], list[list]]:
    rows = [["Date", "Date Created", "KPI", "Quality", "Stage", "ACQ", "Source", "FUS", "Lead Agent",
             "Property Address"]]
    links = [["GHL Link"]]

    def add(row: list, key: str) -> None:
        rows.append(row)
        links.append([LINK.format(key)])

    for i in range(200):  # PPC A, Q3
        month = 7 if i < 60 else 8 if i < 130 else 9
        created = datetime(2026, month, 1 + i % 28, 9)
        q = i % 10
        quality, d = (("Qualified", created + timedelta(days=1)) if q < 4 else
                      ("Disqualified", created + timedelta(days=2)) if q < 9 else ("Pending", None))
        addr = f"{i} Main St, Miami FL 33101" if i < 20 else f"{i} Lead Ln, Miami FL"
        add(_kpi(d, created, "Lead", quality, "PPC A", "Rep A" if i % 2 == 0 else "Rep B", addr), f"A{i}")
    for i in range(10):
        add(_kpi(datetime(2026, 7, 20), datetime(2026, 7, 1 + i % 28, 9), "Appointment Set", "", "PPC A"), f"A{i}")
    for i in range(6):
        add(_kpi(datetime(2026, 7, 25), datetime(2026, 7, 1 + i, 9), "Appointment Held", "", "PPC A"), f"A{i}")
    for i in (6, 7):
        add(_kpi(datetime(2026, 7, 26), datetime(2026, 7, 1 + i, 9), "No-Show", "", "PPC A"), f"A{i}")
    for i in range(3):
        add(_kpi(datetime(2026, 8, 10), datetime(2026, 7, 1 + i, 9), "Closed Deal", "", "PPC A"), f"A{i}")
    for i in range(100):  # PPC A, Q2
        created = datetime(2026, 5, 1 + i % 28, 9)
        quality = "Qualified" if i % 10 < 3 else "Disqualified"
        add(_kpi(created + timedelta(days=1), created, "Lead", quality, "PPC A"), f"Q2_{i}")
    for i in range(10):  # SEO B
        created = datetime(2026, 8, 1 + i, 9)
        quality = "Qualified" if i < 4 else "Disqualified"
        add(_kpi(created + timedelta(days=1), created, "Lead", quality, "SEO B"), f"B{i}")
    add(_kpi(datetime(2026, 7, 2), datetime(2026, 6, 30), "Lead", "Qualified", "SEO B"), "B_jun")
    add(_kpi(None, datetime(2025, 12, 20), "Lead", "Pending", "PPC A"), "OLD1")
    add(_kpi(datetime(2026, 1, 5), datetime(2025, 12, 20), "Lead", "Qualified", "PPC A"), "OLD2")
    return rows, links


def raw_sheet() -> RawSheet:
    kpis, links = _kpis()
    return RawSheet(values={"COSTS": _costs(), "REVENUES": _revenues(), "KPIs": kpis, "KPIS_LINK": links},
                    timezone="America/New_York")
