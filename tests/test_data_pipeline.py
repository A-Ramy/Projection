from datetime import date, datetime

import pytest

from projection.config import DEFAULT_SETTINGS
from projection.data.keys import addr_key, lead_key, street_matches
from projection.data.load import build_dataset
from projection.data.parse import CellError, to_datetime, to_money
from tests.fixtures import COSTS, TODAY, raw_sheet, serial


@pytest.fixture
def ds():
    return build_dataset(raw_sheet(), DEFAULT_SETTINGS, today=TODAY)


def issue(ds, code):
    found = [i for i in ds.issues if i.code == code]
    return found[0] if found else None


# ---------- cell parsing
def test_money_formats():
    assert to_money(1234.5) == 1234.5
    assert to_money("$1,234.56") == 1234.56
    assert to_money("(1,000)") == -1000
    assert to_money("−$4,500") == -4500
    assert to_money("-$4,500.00") == -4500
    assert to_money("") is None and to_money(None) is None
    with pytest.raises(CellError):
        to_money("abc")


def test_serial_and_text_dates():
    assert to_datetime(serial(2026, 1, 1)) == datetime(2026, 1, 1)
    assert to_datetime(serial(2026, 1, 5, 10, 30)) == datetime(2026, 1, 5, 10, 30)
    assert to_datetime("6/27/2026") == datetime(2026, 6, 27)
    assert to_datetime("4/8/2026 19:40:31") == datetime(2026, 4, 8, 19, 40, 31)
    assert to_datetime("  ") is None
    with pytest.raises(CellError):
        to_datetime("not a date")


# ---------- COSTS
def test_costs_filtered_to_start_date_and_bucketed_by_month(ds):
    c = ds.costs
    assert len(c) == 8  # 2026 rows only
    assert c["date"].min() >= datetime(2026, 1, 1)
    assert ds.stats["COSTS"].before_start == 1
    assert ds.stats["COSTS"].blank_rows == 5  # 4 separators + 1 date-only filler
    june = c[c["source"] == "PPC NW RDS"].set_index("month")
    assert june.loc["2026-06", "cost"] == pytest.approx(25000.00)  # dated 6/27, counted in June


def test_text_money_and_blank_cost(ds):
    c = ds.costs
    assert c.loc[c["source"] == "ACQ Payroll", "cost"].item() == pytest.approx(30000.00)
    carrot_feb = c[(c["source"] == "SEO (CARROT)") & (c["month"] == "2026-02")].iloc[0]
    assert carrot_feb["cost"] == 0 and carrot_feb["cost_blank"]
    blank = issue(ds, "blank_cost")
    assert blank.count == 1 and "Feb 2026 · SEO (CARROT)" in blank.examples[0]


def test_non_month_end_dates_reported(ds):
    i = issue(ds, "not_month_end")
    assert any("6/27/2026 → Jun 2026" in e for e in i.examples)


def test_missing_completed_cost_months_reported(ds):
    i = issue(ds, "missing_cost_months")
    assert i.examples == ["Mar 2026", "Apr 2026", "May 2026", "Jul 2026", "Aug 2026", "Sep 2026"]


def test_start_date_is_one_setting():
    ds = build_dataset(raw_sheet(), {**DEFAULT_SETTINGS, "start_date": "2025-12-01"}, today=TODAY)
    assert "2025-12" in set(ds.costs["month"])
    assert "2025-12" in set(ds.revenues["month"])
    assert "2025-12" in set(ds.kpis["month"])


def test_columns_found_by_header_name_not_position():
    shuffled = [[r[i] if i < len(r) else None for i in (2, 0, 1)] for r in COSTS]
    ds = build_dataset(raw_sheet(COSTS=shuffled), DEFAULT_SETTINGS, today=TODAY)
    assert len(ds.costs) == 8


def test_missing_column_is_an_error():
    broken = [["Date", "Cost"]] + [[r[0], r[2]] if len(r) == 3 else [] for r in COSTS[1:]]
    ds = build_dataset(raw_sheet(COSTS=broken), DEFAULT_SETTINGS, today=TODAY)
    i = issue(ds, "missing_columns")
    assert i.severity == "error" and i.examples == ["Source"]


# ---------- names
def test_spacing_and_near_duplicate_spellings_reported_not_merged(ds):
    assert "PPC NW RDS " in set(ds.costs["source"])  # kept exactly as written
    assert issue(ds, "name_spaces").count >= 1
    near = issue(ds, "near_duplicates")
    joined = " ".join(near.examples)
    assert "'PPC NW RDS '" in joined and "'ppc nw rds'" in joined


# ---------- REVENUES
def test_revenues_rows_and_special_values(ds):
    r = ds.revenues
    assert len(r) == 7  # excludes 2025 row and the undated row
    assert issue(ds, "undated_rows") is not None
    assert issue(ds, "zero_revenue").count == 1
    assert issue(ds, "negative_revenue").count == 1
    assert r.loc[r["address"] == "10 Pine Rd", "revenue"].item() == 21000


def test_duplicate_address_written_two_ways(ds):
    i = issue(ds, "duplicate_addresses")
    assert i.count == 1 and "2903 NW 104th Ct" in i.examples[0] and "36,250" in i.examples[0]


def test_revenue_sources_without_leads(ds):
    i = issue(ds, "deals_without_leads")
    assert "SELF GEN" in i.examples and "ppc nw rds" in i.examples
    assert "PPC NW RDS" not in i.examples


# ---------- KPIs
def test_kpis_counted_by_trigger_date_not_created(ds):
    k = ds.kpis
    assert len(k) == 6
    first = k[k["sheet_row"] == 2].iloc[0]
    assert first["month"] == "2026-01" and first["created"].year == 2025  # created in 2025, counts in 2026
    assert ds.stats["KPIs"].before_start == 1


def test_blank_kpi_dates_counted_and_excluded(ds):
    b = ds.blank_kpi_dates
    assert b.count == 2 and b.created_since_start == 1
    assert b.by_quality == {"Pending": 2}  # a Lead row with a blank Quality is Pending
    assert "2 rows with a blank Date" in issue(ds, "blank_kpi_dates").title


def test_lead_rows_kept_by_date_created(ds):
    # rows 3, 4, 6 (dated) and 7 (Pending, blank Date); rows 2, 8, 9 were created before 2026
    assert sorted(ds.leads["sheet_row"]) == [3, 4, 6, 7]
    assert ds.leads.set_index("sheet_row").loc[7, "month"] == "2026-02"
    assert ds.blank_kpi_dates.leads_counted == 1


def test_unknown_kpi_and_other_quality(ds):
    assert "Mystery KPI: 1" in issue(ds, "unknown_kpi").examples
    assert "Pending: 1" in issue(ds, "lead_other_quality").examples
    assert "Lead Assigned" in issue(ds, "missing_stages").examples


def test_no_personal_columns_kept(ds):
    assert not {"Full Name", "Phone", "GHL Link", "address", "name", "phone"} & set(ds.kpis.columns)


# ---------- keys
def test_lead_key_hashes_contact_id():
    a = lead_key("https://app.gohighlevel.com/v2/location/L/contacts/detail/CCC333")
    b = lead_key("https://app.gohighlevel.com/v2/location/L/contacts/detail/CCC333?tab=notes")
    assert a == b and len(a) == 16 and "CCC333" not in a
    assert lead_key("") == ""


def test_same_contact_shares_lead_key(ds):
    k = ds.kpis.set_index("sheet_row")
    assert k.loc[4, "lead_key"] == k.loc[5, "lead_key"] != k.loc[2, "lead_key"]


def test_address_keys_match_street_only_revenue_to_full_kpi_address():
    assert addr_key("3060 SE Fairmont Street, Stuart FL 34997") == "3060 se fairmont st"
    assert addr_key("2903 Northwest 104th Court") == "2903 nw 104th ct"
    assert street_matches(addr_key("3060 SE Fairmont St"), addr_key("3060 SE Fairmont St, Stuart FL"))
    assert street_matches("1057 w 66th st", "1057 w 66th st hialeah fl 33012")
    assert not street_matches("1057 w 66th st", "11057 w 66th st")
    assert date(2026, 1, 1)  # keep date import used


def test_lead_quality_is_qualified_disqualified_or_pending():
    from projection.data.clean import lead_quality

    assert [lead_quality(q) for q in ("Qualified", " disqualified ", "", "Pending", "Hot")] == [
        "Qualified", "Disqualified", "Pending", "Pending", "Pending"]
