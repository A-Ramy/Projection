"""Suggestions: lookback, D1 budget (+ reverse), guardrails, D2 revenue, D3 profit-target plans."""

import math

import pytest

from projection.config import DEFAULT_SETTINGS
from projection.data.load import build_dataset
from projection.metrics.core import cost_complete_months
from projection.model import FOLLOW_UP, CostLine, QuarterProjection, RevenueLine
from projection.periods import Month
from projection.suggest.guardrails import best_quarter_spend
from projection.suggest.lookback import complete_quarters, label, lookback_months
from projection.suggest.marketing import reverse, suggest_budget, suggest_marketing
from projection.suggest.profit_target import (
    SourceEconomics,
    fixed_parts,
    needed_contribution,
    plan_a,
    plan_b,
    plans,
)
from projection.suggest.revenue import suggest_revenue
from tests import metrics_fixture as mf

S = DEFAULT_SETTINGS
JAN_SEP = [Month(2026, m) for m in range(1, 10)]


@pytest.fixture(scope="module")
def ds():
    return build_dataset(mf.raw_sheet(), S, today=mf.TODAY)


@pytest.fixture
def q4():
    return QuarterProjection(
        quarter_id="2026-Q4",
        marketing=[CostLine(source=s) for s in ("PPC A", "SEO B", "Mailer C")],
        non_marketing=[CostLine(source="ACQ Payroll", p_cost=60000)],
        revenue=[
            RevenueLine(block="main", source="PPC A", exit="Wholesale", p_deals=20, p_avg=15000),
            RevenueLine(block="fix_flip", source="PPC A", exit="Fix & Flip", p_deals=5, p_avg=20000),
            RevenueLine(block="main", source="SEO B", exit="Wholesale", p_deals=2, p_avg=12000),
            RevenueLine(block="main", source="Mailer C", exit="Wholesale", p_deals=1, p_avg=10000),
            RevenueLine(block="main", source=FOLLOW_UP, exit="Wholesale", p_deals=1, p_avg=20000),
        ],
    )


# ---------- the required case
def test_budget_37500():
    s = suggest_budget("X", target_deals=25, cost=30000, leads=200, net_leads=80, deals=20, settings=S,
                       best_quarter=30000)
    assert s.cpl == 150 and s.lpd == 10 and s.cost_per_deal == 1500
    assert s.budget == 37500
    assert s.net_cpl == 375 and s.net_lpd == 4  # Net Leads chain gives the same budget: 25 × 4 × 375
    assert 25 * s.net_lpd * s.net_cpl == 37500
    assert s.implied_leads == 250 and s.implied_net_leads == 100
    assert not s.flags.any
    text = "\n".join(s.explain())
    assert "25 deals × 10.00 leads/deal × $150.00 CPL = $37,500.00 (250 leads)" in text
    assert "× 4.00 net leads/deal × $375.00 Net CPL = $37,500.00 (100 net leads)" in text


def test_reverse_of_37500():
    r = reverse(37500, cost=30000, leads=200, deals=20, net_leads=80)
    assert r.implied_leads == 250 and r.implied_deals == 25 and r.implied_net_leads == 100


def test_d1_from_the_sheet(ds, q4):
    months = lookback_months("last_quarter", cost_complete_months(ds))
    got = {s.source: s for s in suggest_marketing(ds, q4, months, S)}
    a = got["PPC A"]
    assert a.target_deals == 25  # 20 Wholesale + 5 Fix & Flip: all its rows in all blocks
    assert (a.cost, a.leads, a.net_leads, a.deals) == (30000, 200, 80, 20) and a.budget == 37500
    assert a.best_quarter == 30000 and not a.flags.any and a.window == "Jul 2026 – Sep 2026"
    b = got["SEO B"]
    assert b.flags.low_confidence and b.budget == 6000
    assert b.flags.scale  # 6,000 > 1.5 × 3,000
    c = got["Mailer C"]
    assert c.flags.insufficient and c.budget is None and c.explain()[0].startswith("Insufficient data")
    assert "ACQ Payroll" not in got  # non-marketing lines get no suggestion


# ---------- guardrails
@pytest.mark.parametrize(("leads", "deals", "target", "flags"), [
    (0, 5, 10, {"insufficient"}),
    (100, 0, 10, {"insufficient"}),
    (29, 5, 1, {"low_confidence"}),
    (100, 2, 1, {"low_confidence"}),
    (30, 3, 1, set()),
    (200, 20, 31, {"scale"}),  # 31 × 1,500 = 46,500 > 1.5 × 30,000
    (200, 20, 30, set()),  # 45,000 is not more than the cap
])
def test_guardrails(leads, deals, target, flags):
    s = suggest_budget("X", target, cost=30000, leads=leads, net_leads=0, deals=deals, settings=S,
                       best_quarter=30000)
    got = {n for n in ("insufficient", "low_confidence", "scale") if getattr(s.flags, n)}
    assert got == flags


def test_guardrail_thresholds_are_settings():
    s = suggest_budget("X", 1, 30000, 40, 0, 4, {**S, "low_conf_min_leads": 50}, best_quarter=30000)
    assert s.flags.low_confidence


def test_best_quarter_spend(ds):
    assert best_quarter_spend(ds.costs, "PPC A", JAN_SEP) == 30000
    assert best_quarter_spend(ds.costs, "PPC A", JAN_SEP[:6]) == 18000
    assert best_quarter_spend(ds.costs, "Nobody", JAN_SEP) == 0


# ---------- lookback
def test_lookback_windows():
    assert lookback_months("last_quarter", JAN_SEP) == JAN_SEP[6:]
    assert lookback_months("last_2_quarters", JAN_SEP) == JAN_SEP[3:]
    assert lookback_months("all", JAN_SEP) == JAN_SEP
    assert lookback_months("custom", JAN_SEP, (Month(2026, 2), Month(2026, 4))) == JAN_SEP[1:4]
    assert label(JAN_SEP[6:]) == "Jul 2026 – Sep 2026"


def test_last_quarter_needs_all_three_months_cost_complete():
    jan_aug = JAN_SEP[:8]
    assert len(complete_quarters(jan_aug)) == 2
    assert lookback_months("last_quarter", jan_aug) == JAN_SEP[3:6]  # Q2, since Sep costs aren't posted
    with pytest.raises(ValueError):
        lookback_months("nonsense", jan_aug)


# ---------- D2
def test_d2_revenue_suggestions(ds, q4):
    months = lookback_months("last_2_quarters", cost_complete_months(ds))
    got = {(s.block, s.source, s.exit): s for s in suggest_revenue(ds, q4, months)}
    w = got[("main", "PPC A", "Wholesale")]
    assert w.quarters == 2 and w.deals == 19 and w.p_deals == 9.5  # 5 in May + 14 in Q3
    assert w.p_avg == pytest.approx(260000 / 19)
    ff = got[("fix_flip", "PPC A", "Fix & Flip")]
    assert ff.p_deals == 1 and ff.p_avg == 17500
    fu = got[("main", FOLLOW_UP, "Wholesale")]
    assert fu.sources == ("SELF GEN",) and fu.p_deals == 0.5 and fu.p_avg == 20000
    assert got[("main", "Mailer C", "Wholesale")].p_deals == 0 and got[("main", "Mailer C", "Wholesale")].p_avg is None


# ---------- D3
def econ():
    return [
        SourceEconomics("S1", cost_per_deal=1000, avg_deal=11000, projected_deals=10, best_quarter=20000),  # max 30
        SourceEconomics("S2", cost_per_deal=2000, avg_deal=7000, projected_deals=10, best_quarter=10000),  # max 7.5
        SourceEconomics("S3", cost_per_deal=500, avg_deal=400, projected_deals=10, best_quarter=1000),  # loses money
    ]


def test_d3_plan_a_most_efficient_first_up_to_caps():
    needed = needed_contribution(target_profit=300000, fixed_costs=100000, fixed_revenue=50000)
    assert needed == 350000
    p = plan_a(needed, econ())
    assert [(x.source, x.deals, x.budget, x.contribution) for x in p.lines] == [
        ("S1", 30, 30000, 300000),  # capped at 30 deals
        ("S2", 7, 14000, 35000),  # capped at 7 whole deals
    ]
    assert p.shortfall == 15000 and p.budget == 44000


def test_d3_plan_a_stops_when_met():
    p = plan_a(55000, econ())
    assert [(x.source, x.deals) for x in p.lines] == [("S1", 6)] and p.shortfall == 0


def test_d3_plan_b_one_factor():
    p = plan_b(350000, econ())
    base = 10 * 10000 + 10 * 5000 + 10 * -100
    assert p.k == pytest.approx(350000 / base)
    lines = {x.source: x for x in p.lines}
    assert lines["S1"].deals == pytest.approx(10 * p.k) and not lines["S1"].over_cap
    assert lines["S2"].over_cap and lines["S3"].over_cap
    assert p.achieved == pytest.approx(350000) and p.shortfall == pytest.approx(0)


def test_d3_plan_b_without_positive_mix_is_all_shortfall():
    p = plan_b(1000, [SourceEconomics("S3", 500, 400, 10, 1000)])
    assert p.k is None and p.lines == [] and p.shortfall == 1000


def test_d3_from_the_sheet(ds, q4):
    assert fixed_parts(q4) == (60000, 5 * 20000 + 20000)  # payroll; PPC A F&F + Follow Up
    months = lookback_months("last_quarter", cost_complete_months(ds))
    a, b = plans(ds, q4, months, S, target_profit=200000)
    assert a.needed == 200000 + 60000 - 120000
    # PPC A: main avg (210,000 + 100,000) / 18; cost per deal 30,000 / 20 deals (all exits)
    first = a.lines[0]
    assert first.source == "PPC A" and first.contribution / first.deals == pytest.approx(310000 / 18 - 1500)
    assert first.deals == math.ceil(140000 / (310000 / 18 - 1500))
    assert b.k is not None and b.shortfall == pytest.approx(0)
