"""Funnel (stage counts, conversions, money per stage) and PTA on the hand-built fixture."""

import pandas as pd
import pytest

from projection.config import DEFAULT_SETTINGS
from projection.data.load import build_dataset
from projection.metrics.funnel import (
    Filters,
    closed_deal_check,
    cohort_conversions,
    cohort_counts,
    conversion_rates,
    conversions,
    stage_counts,
    stage_table,
)
from projection.metrics.pta import lead_to_deal_cohort, rep_table
from projection.periods import Month, quarter
from tests import metrics_fixture as mf

Q3 = quarter(2026, 3)
PPC_A = Filters(sources=("PPC A",))
JUL, AUG, SEP = Month(2026, 7), Month(2026, 8), Month(2026, 9)


@pytest.fixture(scope="module")
def ds():
    return build_dataset(mf.raw_sheet(), DEFAULT_SETTINGS, today=mf.TODAY)


def test_stage_counts_and_net_leads(ds):
    c = stage_counts(ds, Q3.months, PPC_A)
    assert (c["Lead"], c["Net Lead"], c["Appointment Set"], c["Appointment Held"], c["Closed Deal"]) == (
        200, 80, 10, 6, 3)
    assert c["No-show"] == 2  # written "No-Show" in the sheet
    c = stage_counts(ds, Q3.months)
    assert c["Lead"] == 210 and c["Net Lead"] == 85  # + SEO B (one of its net leads was created in June)


def test_stage_names_match_case_insensitively(ds):
    codes = {i.code: i for i in ds.issues}
    assert "unknown_kpi" not in codes
    assert "No-show" not in codes["missing_stages"].examples


def test_period_conversions(ds):
    conv = conversions(stage_counts(ds, Q3.months, PPC_A)).set_index(["from", "to"])
    assert conv.loc[("Lead", "Appointment Set"), "rate"] == 0.05
    assert conv.loc[("Appointment Set", "Appointment Held"), "rate"] == 0.6
    assert conv.loc[("Lead", "Net Lead"), "rate"] == 0.4
    assert pd.isna(conv.loc[("Contract Sent", "Contract Signed"), "rate"])  # nothing to convert from


def test_cohort_conversions(ds):
    pairs = [("Appointment Set", "Appointment Held"), ("Lead", "Net Lead"), ("Lead", "Closed Deal")]
    co = cohort_conversions(ds, [JUL, SEP], PPC_A, pairs).set_index(["month", "from", "to"])
    assert co.loc[("2026-07", "Appointment Set", "Appointment Held"), ["cohort", "converted"]].tolist() == [10, 6]
    assert co.loc[("2026-07", "Lead", "Net Lead"), "rate"] == 0.4  # 24 of the 60 July leads
    assert co.loc[("2026-07", "Lead", "Closed Deal"), "converted"] == 3
    assert not co.loc[("2026-07", "Lead", "Net Lead"), "immature"]
    assert co.loc[("2026-09", "Lead", "Net Lead"), "immature"]  # within 2 months of today


def test_stage_table_company_wide(ds):
    t = stage_table(ds, Q3, DEFAULT_SETTINGS).set_index("stage")
    assert t.attrs["cost_months"] == ["2026-07", "2026-08", "2026-09"]
    lead = t.loc["Lead"]
    assert lead["count"] == 210
    assert lead["cost_per"] == pytest.approx(35000 / 210)  # marketing: PPC A + SEO B + Mailer C
    assert lead["all_in_cost_per"] == pytest.approx(95000 / 210)  # incl. payroll
    assert lead["revenue_per"] == pytest.approx(415000 / 210)
    assert lead["profit_per"] == pytest.approx((415000 - 35000) / 210)
    assert lead["all_in_profit_per"] == pytest.approx((415000 - 95000) / 210)
    assert t.loc["Net Lead", "from_previous"] == pytest.approx(85 / 210)
    assert t.loc["No-show", "path"] == "leakage" and t.loc["No-show", "from_previous"] == pytest.approx(2 / 10)
    assert t.loc["No-show", "previous"] == "Appointment Set"


def test_stage_table_by_source_and_by_rep(ds):
    t = stage_table(ds, Q3, DEFAULT_SETTINGS, PPC_A).set_index("stage")
    assert t.loc["Lead", "cost_per"] == 150 and t.loc["Lead", "revenue_per"] == 345000 / 200
    assert t.loc["Lead", "profit_per"] == (345000 - 30000) / 200
    assert pd.isna(t.loc["Lead", "all_in_cost_per"])  # company-wide only
    rep_a = Filters(sources=("PPC A",), rep_col="acq", rep="Rep A")
    t = stage_table(ds, Q3, DEFAULT_SETTINGS, rep_a).set_index("stage")
    assert t.loc["Lead", "count"] == 100 and pd.isna(t.loc["Lead", "cost_per"])  # costs aren't per rep


def test_closed_deal_kpi_vs_revenues(ds):
    chk = closed_deal_check(ds, Q3.months, PPC_A)
    assert (chk.kpi_closed, chk.revenue_deals, chk.gap, chk.mismatch) == (3, 20, 17, True)


def test_pta_rep_table(ds):
    t = rep_table(ds, Q3.months, "ACQ", sources=("PPC A",))
    a, b = t.loc["Rep A"], t.loc["Rep B"]
    assert (a["leads"], a["qualified"], a["disqualified"], a["deals"], a["revenue"]) == (100, 40, 60, 12, 180000)
    assert (b["leads"], b["disqualified"], b["deals"], b["revenue"]) == (100, 40, 8, 165000)
    assert a["qual_rate"] == 0.4 and a["lead_to_deal"] == 0.12 and a["avg_deal"] == 15000
    assert t.loc["(blank)", "Appointment Set"] == 10  # funnel rows in the fixture carry no ACQ


def test_lead_to_deal_cohort(ds):
    co = lead_to_deal_cohort(ds, [JUL, AUG], PPC_A).set_index("month")
    assert co.loc["2026-07", ["addresses", "closed"]].tolist() == [60, 20]  # the 20 Main St leads closed later
    assert co.loc["2026-08", "closed"] == 0


def test_cohort_counts_follow_the_period_leads(ds):
    c = cohort_counts(ds, [JUL], PPC_A)  # 60 July leads
    assert c["Lead"] == 60 and c["Net Lead"] == 24
    assert (c["Appointment Set"], c["Appointment Held"], c["No-show"], c["Closed Deal"]) == (10, 6, 2, 3)
    assert cohort_counts(ds, [AUG], PPC_A)["Appointment Set"] == 0  # August leads had no appointments


def test_conversion_rates_period_and_cohort(ds):
    pairs = [("Appointment Set", "Appointment Held"), ("Lead", "Closed Deal")]
    per = conversion_rates(ds, Q3.months, PPC_A, "period", pairs).set_index(["from", "to"])
    assert per.loc[("Lead", "Closed Deal"), "rate"] == 3 / 200
    co = conversion_rates(ds, Q3.months, PPC_A, "cohort", pairs).set_index(["from", "to"])
    assert co.loc[("Appointment Set", "Appointment Held"), "rate"] == 0.6
    assert co.loc[("Lead", "Closed Deal"), ["from_count", "to_count"]].tolist() == [200, 3]


def test_stage_table_cohort_method(ds):
    t = stage_table(ds, [JUL], DEFAULT_SETTINGS, PPC_A, method="cohort").set_index("stage")
    assert t.loc["Lead", "count"] == 60 and t.loc["Appointment Held", "from_previous"] == 0.6


def test_leaderboard_period_and_cohort(ds):
    from projection.metrics.pta import LEADERBOARD, leaderboard

    lb = leaderboard(ds, Q3.months, "ACQ", sources=("PPC A",))
    assert list(lb.columns) == LEADERBOARD
    a = lb.loc["Rep A"]
    assert (a["Leads"], a["Net Leads"], a["Deals"], a["Revenue"], a["Lead→Deal"]) == (100, 40, 12, 180000, 0.12)
    co = leaderboard(ds, [JUL], "ACQ", sources=("PPC A",), conversion="cohort")
    assert co.loc["Rep A", "Lead→Deal"] == 10 / 30  # even leads 0–18 of the 30 July Rep A leads later closed


def test_periods_in_range():
    from projection.periods import periods_in_range

    ps = periods_in_range(Month(2026, 2), Month(2026, 7), "quarter")
    assert [p.label for p in ps] == ["Q1 2026", "Q2 2026", "Q3 2026"]
    assert [len(p.months) for p in ps] == [2, 3, 1]


def test_pta_empty_period(ds):
    from projection.metrics.pta import leaderboard

    assert leaderboard(ds, [Month(2026, 3)], "ACQ", sources=("SEO B",)).empty
    assert rep_table(ds, [Month(2026, 3)], "FUS").shape[0] >= 0
