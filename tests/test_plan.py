"""Projecting from the backbone (tests/metrics_fixture.py; Q4 2026 built on Q3 2026 actuals)."""

import pytest

from projection.config import DEFAULT_SETTINGS
from projection.data.load import build_dataset
from projection.metrics.quarter import quarter_view
from projection.model import FOLLOW_UP, QuarterProjection
from projection.periods import quarter
from projection.plan import (
    FOLLOW_UP_KIND,
    NO_COST,
    backbone,
    prefill,
    set_driver,
    source_rows,
    split_by_mix,
    totals,
    use_plan,
)
from projection.suggest.profit_target import Plan, PlanLine
from tests import metrics_fixture as mf

S = DEFAULT_SETTINGS
Q4 = quarter(2026, 4)


@pytest.fixture(scope="module")
def ds():
    return build_dataset(mf.raw_sheet(), S, today=mf.TODAY)


@pytest.fixture
def p(ds):
    return prefill(ds, Q4, S, QuarterProjection(quarter_id="2026-Q4"))


def rows(ds, p):
    return {r.source: r for r in source_rows(p, backbone(ds, p, Q4), S)}


def test_prefill_repeats_the_backbone(ds, p):
    assert [c.source for c in p.marketing] == ["PPC A", "SEO B", "Mailer C", "SELF GEN"]
    assert [(r.source, r.exit, r.p_deals, r.p_avg) for r in p.revenue] == [
        ("PPC A", "Novation Deal", 4, 25000), ("PPC A", "Wholesale", 14, 15000), ("PPC A", "Fix & Flip", 2, 17500),
        ("SEO B", "Wholesale", 1, 12000), ("SELF GEN", "Retail Listing", 1, 8000), ("SELF GEN", "Wholesale", 1, 20000),
        (FOLLOW_UP, "Fix & Flip", 1, 30000)]
    assert {c.source: c.p_cost for c in p.non_marketing}["ACQ Payroll"] == 60000
    assert {c.source: c.p_cost for c in p.marketing} == {"PPC A": 30000, "SEO B": 3000, "Mailer C": 2000,
                                                          "SELF GEN": 0}
    t = totals(p, source_rows(p, backbone(ds, p, Q4), S))
    assert (t["revenue"], t["cost"], t["profit"], t["deals"]) == (415000, 95000, 320000, 24)  # = Q3 actuals


def test_backbone_units(ds, p):
    r = rows(ds, p)
    a = r["PPC A"]
    assert (a.unit.cpd, a.unit.avg, a.unit.leads, a.deals, a.unallocated) == (1500, 17250, 200, 20, 0)
    assert r["SELF GEN"].kind == NO_COST and r["SELF GEN"].spend == 0 and r["SELF GEN"].deals == 2
    fu = r[FOLLOW_UP]
    assert fu.kind == FOLLOW_UP_KIND and fu.unit.avg == 30000 and fu.spend == 0
    m = r["Mailer C"]  # spent but never closed a deal, even in the longer window
    assert m.deals is None and m.spend == 2000 and any("type deals" in n for n in m.notes)


def test_spend_driver_then_split_by_mix(ds, p):
    bb = backbone(ds, p, Q4)
    set_driver(p, "PPC A", "spend", 45000, bb, S)
    a = rows(ds, p)["PPC A"]
    assert (a.deals, a.revenue, a.unallocated) == (30, 517500, 10)
    assert next(c for c in p.marketing if c.source == "PPC A").p_cost == 45000
    split_by_mix(p, "PPC A", bb, S)
    exits = {r.exit: r.p_deals for r in p.revenue if r.source == "PPC A"}
    assert exits == {"Wholesale": 21, "Novation Deal": 6, "Fix & Flip": 3}
    assert rows(ds, p)["PPC A"].unallocated == 0


def test_revenue_and_deals_drivers_work_back_the_spend(ds, p):
    bb = backbone(ds, p, Q4)
    set_driver(p, "PPC A", "revenue", 172500, bb, S)
    a = rows(ds, p)["PPC A"]
    assert (a.deals, a.spend) == (10, 15000)
    set_driver(p, "PPC A", "deals", 25, bb, S)
    assert rows(ds, p)["PPC A"].spend == 37500  # the required 25 × $1,500 case
    set_driver(p, FOLLOW_UP, "deals", 3, bb, S)
    fu = rows(ds, p)[FOLLOW_UP]
    assert (fu.deals, fu.revenue, fu.unallocated, fu.spend) == (3, 90000, 2, 0)
    t = totals(p, source_rows(p, bb, S))
    # unplaced deals already count: PPC A 5 × $17,250 (25 set, 20 placed) + Follow Up 2 × $30,000
    assert t["not_placed"] == 5 * 17250 + 2 * 30000


def test_exits_driver_follows_the_rows(ds, p):
    bb = backbone(ds, p, Q4)
    set_driver(p, "PPC A", "exits", 0, bb, S)
    next(r for r in p.revenue if r.source == "PPC A" and r.exit == "Wholesale").p_deals = 24
    assert rows(ds, p)["PPC A"].deals == 30 and rows(ds, p)["PPC A"].spend == 45000


def test_actuals_reconcile_and_projected_sources_stay_out_of_follow_up(ds, p):
    v = quarter_view(ds, p, quarter(2026, 3), S)  # the Q4 plan laid over Q3's actuals
    fu = [x for x in v.revenue if x.source == FOLLOW_UP]
    assert {s for x in fu for s in x.contributors} == {"Inbound X"}
    assert v.a_revenue == 415000


def test_use_plan_sets_deals_drivers(ds, p):
    bb = backbone(ds, p, Q4)
    use_plan(p, Plan("A", 0, [PlanLine("PPC A", 36, 54000, 0)]), bb, S)
    assert p.drivers["PPC A"].kind == "deals" and next(c for c in p.marketing if c.source == "PPC A").p_cost == 54000


def test_backbone_fallback_only_for_typed_numbers(ds):
    # a source with spend but no deals in the backbone keeps 0 deals until you type a number for it
    from projection.model import CostLine, Driver
    from projection.plan import Unit, derive

    u = Unit("X", cost=1000, cpd=500, avg=10000, fallback=True)
    assert derive(Driver(kind="spend", value=1000), u, 0) == (1000, None, None)  # pre-filled: repeats the backbone
    assert derive(Driver(kind="spend", value=2000, typed=True), u, 0) == (2000, 4, 40000)  # typed: longer window
    assert CostLine(source="X").p_cost == 0
