"""A small raw-sheet fixture shaped like the Sheets API response (UNFORMATTED values).

Covers: rows before the start date, blank separator rows, date-only filler rows, text money and
dates, a blank cost cell, a non-month-end date (6/27), a trailing-space and a lowercase source
spelling, a duplicate address written two ways, $0 and negative revenue, an undated revenue row,
blank KPI dates, a non-Qualified/Disqualified dated Lead and an unknown KPI value.
"""

from __future__ import annotations

from datetime import date, datetime

from projection.sheets import RawSheet

EPOCH = datetime(1899, 12, 30)


def serial(y: int, m: int, d: int, hh: int = 0, mm: int = 0) -> float:
    return (datetime(y, m, d, hh, mm) - EPOCH).total_seconds() / 86400


COSTS = [
    ["Date", "Source", "Cost"],
    ["", "", ""],
    [serial(2025, 12, 30), "PPC NW RDS", 19000.00],  # before start
    [serial(2025, 1, 31), "", ""],  # date-only filler line
    [],
    [serial(2026, 1, 31), "PPC NW RDS", 20000.00],
    [serial(2026, 1, 31), "ACQ Payroll", "$30,000.00"],  # text money
    [serial(2026, 1, 31), "SEO (CARROT)", 3000],
    [],
    [serial(2026, 2, 28), "PPC NW RDS", 21000.00],
    [serial(2026, 2, 28), "SEO (CARROT)"],  # blank cost (short row)
    [serial(2026, 2, 28), "PPC NW RDS ", 10],  # trailing space
    [],
    ["6/27/2026", "PPC NW RDS", 25000.00],  # text date, not month end
    [serial(2026, 6, 27), "Facebook Ads (AM)", 8000.00],
]

REVENUES = [
    ["Date Closed", "Address", "Source", "Revenue", "Exit Strategy", "AGENT", "FUS", "ACQ", "DISPO", "DISPO LM"],
    [serial(2025, 12, 15), "1 Old St", "PPC NW RDS", 10000, "Wholesale", "", "Rep D", "Rep A", "", ""],
    [],
    [serial(2026, 1, 10), "2903 NW 104th Ct", "SMS (Smarter Contact)", 2500, "Fix & Flip", "", "Rep D", "Rep A", "", ""],
    [serial(2026, 2, 12), "2903 Northwest 104th Court", "SMS (Smarter Contact)", 36250, "Fix & Flip", "", "Rep D",
     "Rep A", "Rep X", ""],
    [serial(2026, 2, 20), "55 Elm St", "PPC NW RDS", 0, "Retail Listing", "", "Rep E", "Rep B", "", ""],
    [serial(2026, 3, 5), "9 Oak Ave", "PPC NW RDS", -4500, "Fix & Flip", "", "Rep E", "Rep B", "", ""],
    [serial(2026, 3, 6), "10 Pine Rd", "SELF GEN", "$21,000", "Wholesale", "", "", "Rep A", "", ""],
    [serial(2026, 3, 7), "3060 SE Fairmont St", "PPC NW RDS", 30000, "Novation Deal", "", "Rep D", "Rep A", "", ""],
    [serial(2026, 3, 8), "12 Sea Ln", "ppc nw rds", 15000, "Wholesale", "", "Rep D", "Rep C", "", ""],
    ["", "13 No Date St", "PPC NW RDS", 1000, "Wholesale", "", "", "", "", ""],
]

KPIS = [
    ["Date", "Date Created", "KPI", "Quality", "Stage", "ACQ", "Source", "FUS", "Lead Agent", "Property Address"],
    [serial(2026, 1, 5, 10, 30), serial(2025, 11, 2), "Lead", "Qualified", "", "Rep A", "PPC NW RDS", "Rep D", "",
     "3060 SE Fairmont St, Stuart FL 34997"],
    [serial(2026, 1, 6), serial(2026, 1, 6), "Lead", "Disqualified", "Dead", "Rep B", "PPC NW RDS", "Rep E", "",
     "55 Elm St, Miami FL"],
    [serial(2026, 1, 7), serial(2026, 1, 7), "Lead", "Qualified", "", "Rep A", "SMS (Smarter Contact)", "Rep D", "",
     "2903 NW 104th Ct, Miami FL"],
    [serial(2026, 2, 1), serial(2026, 1, 7), "Appointment Set", "Qualified", "", "Rep A", "SMS (Smarter Contact)",
     "Rep D", "", "2903 NW 104th Ct, Miami FL"],
    [serial(2026, 2, 3), serial(2026, 2, 3), "Lead", "Pending", "", "Rep C", "SEO (CARROT)", "", "", ""],
    ["", serial(2026, 2, 10), "Lead", "Pending", "", "", "PPC NW RDS", "", "", ""],
    ["", serial(2025, 5, 1), "Lead", "", "", "", "PPC NW RDS", "", "", ""],
    [serial(2025, 12, 31), serial(2025, 12, 1), "Lead", "Qualified", "", "Rep A", "PPC NW RDS", "", "", ""],
    [serial(2026, 3, 1), serial(2026, 3, 1), "Mystery KPI", "", "", "Rep B", "PPC NW RDS", "", "", ""],
]

# Column M (GHL Link), aligned to the KPIs rows above (row 1 = header)
KPIS_LINK = [
    ["GHL Link"],
    ["https://app.gohighlevel.com/v2/location/LOC1/contacts/detail/AAA111"],
    ["https://app.gohighlevel.com/v2/location/LOC1/contacts/detail/BBB222"],
    ["https://app.gohighlevel.com/v2/location/LOC1/contacts/detail/CCC333"],
    ["https://app.gohighlevel.com/v2/location/LOC1/contacts/detail/CCC333?tab=notes"],  # same contact
    [""],
    ["https://app.gohighlevel.com/v2/location/LOC1/contacts/detail/DDD444"],
    [""],
    ["https://app.gohighlevel.com/v2/location/LOC1/contacts/detail/EEE555"],
    ["https://app.gohighlevel.com/v2/location/LOC1/contacts/detail/FFF666"],
]

TODAY = date(2026, 10, 14)


def raw_sheet(**overrides) -> RawSheet:
    values = {"COSTS": COSTS, "REVENUES": REVENUES, "KPIs": KPIS, "KPIS_LINK": KPIS_LINK}
    values.update(overrides)
    return RawSheet(values=values, timezone="America/New_York")
