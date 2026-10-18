"""Suggestions for a quarter: the window never includes the quarter itself; accept, override and drift."""

import pytest

from projection.config import DEFAULT_SETTINGS
from projection.data.load import build_dataset
from projection.model import CostLine, QuarterProjection, RevenueLine
from projection.periods import Month, quarter
from projection.suggest.quarter import (
    accept_budget,
    accept_revenue,
    budget_drift,
    history_months,
    mark_typed,
    quarter_suggestions,
)
from tests import metrics_fixture as mf

S = DEFAULT_SETTINGS


@pytest.fixture(scope="module")
def ds():
    return build_dataset(mf.raw_sheet(), S, today=mf.TODAY)


def proj(qid: str, **kw) -> QuarterProjection:
    return QuarterProjection(
        quarter_id=qid, marketing=[CostLine(source="PPC A"), CostLine(source="Mailer C")],
        revenue=[RevenueLine(block="main", source="PPC A", exit="Wholesale", p_deals=20),
                 RevenueLine(block="fix_flip", source="PPC A", exit="Fix & Flip", p_deals=5)], **kw)


def test_window_is_before_the_quarter(ds):
    assert history_months(ds, quarter(2026, 4), proj("2026-Q4")) == [Month(2026, m) for m in (7, 8, 9)]
    assert history_months(ds, quarter(2026, 3), proj("2026-Q3")) == [Month(2026, m) for m in (4, 5, 6)]
    assert history_months(ds, quarter(2026, 1), proj("2026-Q1")) == []  # nothing before the start date
    assert history_months(ds, quarter(2026, 4), proj("2026-Q4", lookback="all"))[-1] == Month(2026, 9)
    custom = proj("2026-Q4", lookback="custom", lookback_from="2026-02", lookback_to="2026-03")
    assert history_months(ds, quarter(2026, 4), custom) == [Month(2026, 2), Month(2026, 3)]
    assert history_months(ds, quarter(2026, 4), proj("2026-Q4", lookback="custom")) == []


def test_q4_suggestions_and_accept(ds):
    p = proj("2026-Q4")
    sug = quarter_suggestions(ds, p, quarter(2026, 4), S)
    assert sug.window == "Jul 2026 – Sep 2026"
    a = sug.budgets["PPC A"]
    assert a.budget == 37500
    assert accept_budget(p.marketing[0], a) and p.marketing[0].p_cost == 37500
    assert p.marketing[0].origin == "accepted_suggestion" and p.marketing[0].inputs["target_deals"] == 25
    assert not accept_budget(p.marketing[1], sug.budgets["Mailer C"])  # insufficient data: nothing to accept
    assert p.marketing[1].p_cost == 0 and p.marketing[1].origin == "manual"
    w = sug.revenue[("main", "PPC A", "Wholesale")]
    assert accept_revenue(p.revenue[0], w) and (p.revenue[0].p_deals, p.revenue[0].p_avg) == (14, 15000)


def test_q3_learns_from_q2(ds):
    sug = quarter_suggestions(ds, proj("2026-Q3"), quarter(2026, 3), S)
    a = sug.budgets["PPC A"]
    assert (a.cost, a.leads, a.deals, a.cost_per_deal) == (18000, 100, 5, 3600)


def test_typing_over_a_suggestion_is_an_override_and_drift_is_flagged_not_applied(ds):
    p = proj("2026-Q4")
    sug = quarter_suggestions(ds, p, quarter(2026, 4), S)
    line = p.marketing[0]
    accept_budget(line, sug.budgets["PPC A"])
    assert budget_drift(line, sug.budgets["PPC A"]) is None
    p.revenue[0].p_deals = 30  # more target deals -> a new suggestion, the accepted value stays
    newer = quarter_suggestions(ds, p, quarter(2026, 4), S).budgets["PPC A"]
    assert budget_drift(line, newer) == 52500 and line.p_cost == 37500
    mark_typed(line)
    assert line.origin == "override" and budget_drift(line, newer) is None
    manual = CostLine(source="X")
    mark_typed(manual)
    assert manual.origin == "manual"
