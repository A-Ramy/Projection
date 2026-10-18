"""Backtest on the hand-built fixture: Q3 2026 predicted from Q2 (last quarter) or Q1–Q2."""

import pytest

from projection.backtest import backtest
from projection.config import DEFAULT_SETTINGS
from projection.data.load import build_dataset
from projection.periods import quarter
from tests import metrics_fixture as mf


@pytest.fixture(scope="module")
def ds():
    return build_dataset(mf.raw_sheet(), DEFAULT_SETTINGS, today=mf.TODAY)


def test_q3_from_q2(ds):
    bt = backtest(ds, quarter(2026, 3), DEFAULT_SETTINGS, "last_quarter")
    assert bt.window_label == "Apr 2026 – Jun 2026"
    rows = {r.source: r for r in bt.rows}
    a = rows["PPC A"]  # Q2: $18,000, 100 leads, 5 deals, $50,000 -> Q3 actual: $30,000, 200 leads, 20 deals
    assert (a.pred_deals, a.pred_budget, a.pred_leads, a.pred_revenue) == (5, 18000, 100, 50000)
    assert a.error("deals") == pytest.approx((5 - 20) / 20) and a.error("budget") == pytest.approx(-0.4)
    assert not rows["SEO B"].predictable and rows["SEO B"].note == "No spend in the window"
    assert bt.mape("deals") == pytest.approx(0.75)


def test_budget_with_actual_deals(ds):
    bt = backtest(ds, quarter(2026, 3), DEFAULT_SETTINGS, "last_quarter", actual_deals_basis=True)
    a = {r.source: r for r in bt.rows}["PPC A"]
    assert a.pred_budget == 20 * 3600  # Q3's 20 deals × Q2 cost per deal


def test_two_quarter_window(ds):
    bt = backtest(ds, quarter(2026, 3), DEFAULT_SETTINGS, "last_2_quarters")
    a = {r.source: r for r in bt.rows}["PPC A"]
    assert a.quarters == 2 and a.pred_deals == 4  # (3 + 5) / 2
