"""Metrics engine on the hand-built fixture (tests/metrics_fixture.py); every expected number is worked by hand."""

import pytest

from projection.config import DEFAULT_SETTINGS
from projection.data.load import build_dataset
from projection.metrics.core import by_source, cost_complete_months, rollup, source_month
from projection.metrics.follow_up import FOLLOW_UP_KIND, PROJECTED, UNPROJECTED, revenue_actuals
from projection.metrics.pacing import cost_pace, daily_pace
from projection.metrics.quarter import OTHER_MARKETING_LABEL, quarter_view
from projection.model import FOLLOW_UP, CostLine, QuarterProjection, RevenueLine
from projection.periods import Month, quarter
from tests import metrics_fixture as mf

Q2, Q3, Q4 = quarter(2026, 2), quarter(2026, 3), quarter(2026, 4)


@pytest.fixture(scope="module")
def ds():
    return build_dataset(mf.raw_sheet(), DEFAULT_SETTINGS, today=mf.TODAY)


@pytest.fixture
def q3_projection():
    return QuarterProjection(
        quarter_id="2026-Q3",
        marketing=[CostLine(source="PPC A", p_cost=28000), CostLine(source="SEO B", p_cost=3000)],
        non_marketing=[CostLine(source="ACQ Payroll", p_cost=60000)],
        revenue=[
            RevenueLine(block="main", source="PPC A", exit="Wholesale", p_deals=12, p_avg=15000),
            RevenueLine(block="main", source="SEO B", exit="Wholesale", p_deals=1, p_avg=10000),
            RevenueLine(block="main", source=FOLLOW_UP, exit="Wholesale", p_deals=1, p_avg=15000),
            RevenueLine(block="fix_flip", source=FOLLOW_UP, exit="Fix & Flip", p_deals=1, p_avg=30000),
        ],
    )


# ---------- leads: All Leads by Date Created (incl. Pending), Net Leads by the Quality date
def test_all_leads_by_date_created_including_pending(ds):
    assert len(ds.leads) == 311  # 200 + 100 PPC A, 11 SEO B; the two leads created in 2025 are out
    assert ds.leads["date"].isna().sum() == 20  # Pending: counted although they have no Date
    assert ds.blank_kpi_dates.leads_counted == 20 and ds.blank_kpi_dates.count == 21


def test_lead_created_in_june_qualified_in_july(ds):
    seo = by_source(ds, Q2.months).loc["SEO B"]
    assert seo["leads"] == 1 and seo["net_leads"] == 0
    seo = by_source(ds, Q3.months).loc["SEO B"]
    assert seo["leads"] == 10 and seo["net_leads"] == 5


def test_lead_created_before_start_counts_only_as_net_lead(ds):
    q1 = by_source(ds, quarter(2026, 1).months).loc["PPC A"]
    assert q1["leads"] == 0 and q1["net_leads"] == 1


def test_source_parts_and_ratios_q3(ds):
    a = by_source(ds, Q3.months).loc["PPC A"]
    assert (a["cost"], a["leads"], a["net_leads"], a["deals"], a["revenue"]) == (30000, 200, 80, 20, 345000)
    assert a["cpl"] == 150 and a["net_cpl"] == 375 and a["lpd"] == 10 and a["net_lpd"] == 4
    assert a["cost_per_deal"] == 1500 and a["avg_deal"] == 17250 and a["qual_rate"] == 0.4


def test_ratios_recomputed_from_summed_parts_not_averaged(ds):
    monthly = source_month(ds)
    a = monthly[(monthly["source"] == "PPC A") & monthly["month"].isin(["2026-07", "2026-08", "2026-09"])]
    assert list(a["leads"]) == [60, 70, 70]
    q = rollup(monthly, "quarter", by=["source"]).loc[("2026-Q3", "PPC A")]
    assert q["cpl"] == 150  # 30,000 / 200, not the mean of 166.67, 142.86, 142.86
    assert rollup(monthly, "year", by=["source"]).loc[("2026", "PPC A"), "cost"] == 15000 + 18000 + 30000


def test_cost_complete_months(ds):
    assert cost_complete_months(ds) == [Month(2026, m) for m in range(1, 10)]


# ---------- Follow Up roll-up per block, with the "(unprojected)" exit row
def test_follow_up_rollup_reconciles(ds, q3_projection):
    lines = {(x.block, x.label, x.exit): x for x in revenue_actuals(ds, q3_projection, Q3.months)}
    got = {k: (x.kind, x.a_deals, x.a_revenue) for k, x in lines.items()}
    assert got == {
        ("main", "PPC A", "Wholesale"): (PROJECTED, 14, 210000),
        ("main", "SEO B", "Wholesale"): (PROJECTED, 1, 12000),
        ("main", "PPC A (unprojected)", "Novation Deal"): (UNPROJECTED, 4, 100000),
        ("main", FOLLOW_UP, "Wholesale"): (FOLLOW_UP_KIND, 1, 20000),
        ("main", FOLLOW_UP, "Retail Listing"): (FOLLOW_UP_KIND, 1, 8000),
        # PPC A has no Fix & Flip row, so its F&F deals roll into that block's Follow Up
        ("fix_flip", FOLLOW_UP, "Fix & Flip"): (FOLLOW_UP_KIND, 3, 65000),
    }
    assert lines[("fix_flip", FOLLOW_UP, "Fix & Flip")].contributors == {"PPC A": [2, 35000], "Inbound X": [1, 30000]}
    assert sum(x.a_revenue for x in lines.values()) == 415000  # = all Q3 revenue
    assert sum(x.a_deals for x in lines.values()) == 24
    pa = lines[("main", "PPC A", "Wholesale")]
    assert pa.p_revenue == 180000 and pa.pva_revenue == 30000 and pa.a_avg == 15000


# ---------- the quarter view: cost lines, P.% / A.%, profit
def test_quarter_view_complete_quarter(ds, q3_projection):
    v = quarter_view(ds, q3_projection, Q3, DEFAULT_SETTINGS)
    assert v.complete and v.costs_label == "costs for the full quarter"
    c = {x.source: x for x in v.costs}
    assert (c["PPC A"].p_cost, c["PPC A"].a_cost, c["PPC A"].pva_cost) == (28000, 30000, -2000)
    assert c["ACQ Payroll"].a_cost == 60000
    assert c[OTHER_MARKETING_LABEL].a_cost == 2000 and c[OTHER_MARKETING_LABEL].contributors == {"Mailer C": 2000}
    assert v.p_cost == 91000 and v.a_cost == 95000
    # % base excludes Fix & Flip and Buy & Hold on both sides
    assert v.p_base == 205000 and v.a_base == 350000
    assert c["PPC A"].p_pct == pytest.approx(28000 / 205000) and c["PPC A"].a_pct == pytest.approx(30000 / 350000)
    assert c["PPC A"].pva_pct == pytest.approx(28000 / 205000 - 30000 / 350000)
    assert v.a_revenue == 415000 and v.a_profit == 320000 and v.a_margin == pytest.approx(320000 / 415000)
    assert v.p_revenue == 235000 and v.p_profit == 144000


def test_pct_base_setting(ds, q3_projection):
    v = quarter_view(ds, q3_projection, Q3, {**DEFAULT_SETTINGS, "pct_base_excluded_exits": []})
    assert v.a_base == 415000 and v.p_base == 235000


def test_quarter_in_progress_has_no_costs_yet(ds):
    p = QuarterProjection(quarter_id="2026-Q4", marketing=[CostLine(source="PPC A", p_cost=40000)],
                          revenue=[RevenueLine(block="main", source="PPC A", exit="Wholesale", p_deals=10,
                                               p_avg=27600)])
    v = quarter_view(ds, p, Q4, DEFAULT_SETTINGS)
    assert v.cost_months == [] and v.costs_label == "no cost month complete yet"
    assert v.a_cost == 0 and v.a_revenue == 18000  # revenue runs to today
    assert v.a_revenue_cost_months == 0 and v.a_pct is None


# ---------- pacing
def test_pacing_with_zero_completed_cost_months():
    rev = daily_pace(Q4, mf.TODAY, projected=276000, actual=18000)
    assert rev.expected_to_date == pytest.approx(42000)  # 14 of 92 days
    assert rev.forecast == pytest.approx(18000 / 14 * 92) and rev.basis == "14 of 92 days"
    cost = cost_pace(Q4, [], projected=40000, actual=0)
    assert cost.expected_to_date == 0 and cost.forecast == 40000 and "forecast = projected" in cost.basis


def test_cost_pacing_with_two_complete_months():
    p = cost_pace(Q3, [Month(2026, 7), Month(2026, 8)], projected=90000, actual=50000)
    assert p.expected_to_date == 60000 and p.forecast == 75000 and p.basis == "costs through Aug 2026"
    assert p.vs_expected == -10000
