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

S = {**DEFAULT_SETTINGS, "active_sources": ["PPC A", "SEO B", "Mailer C", "SELF GEN"]}
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
        ("PPC A", "Novation", 4, 25000), ("PPC A", "Wholesale", 14, 15000), ("PPC A", "Fix & Flip", 2, 17500),
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
    assert m.deals is None and m.spend == 2000 and any("tick Manual" in n for n in m.notes)


def test_spend_driver_places_whole_deals_on_the_exit_rows(ds, p):
    bb = backbone(ds, p, Q4)
    set_driver(p, "PPC A", "spend", 45000, bb, S)
    a = rows(ds, p)["PPC A"]
    assert (a.deals, a.revenue, a.unallocated, a.spend) == (30, 517500, 0, 45000)
    assert next(c for c in p.marketing if c.source == "PPC A").p_cost == 45000
    exits = {r.exit: r.p_deals for r in p.revenue if r.source == "PPC A"}
    assert exits == {"Novation": 6, "Wholesale": 21, "Fix & Flip": 3}  # 4 : 14 : 2 kept
    set_driver(p, "PPC A", "spend", 46000, bb, S)  # 30.67 deals -> 31, spend = 31 × $1,500
    a = rows(ds, p)["PPC A"]
    assert (a.deals, a.spend) == (31, 46500)
    assert {r.exit: r.p_deals for r in p.revenue if r.source == "PPC A"} == {
        "Novation": 6, "Wholesale": 22, "Fix & Flip": 3}
    split_by_mix(p, "PPC A", bb, S)
    assert sum(r.p_deals for r in p.revenue if r.source == "PPC A") == 31


def test_whole_deals_and_spread():
    from projection.plan import spread, whole

    assert (whole(23.28), whole(23.5), whole(-2)) == (23, 24, 0)
    assert spread(17, [4, 12]) == [4, 13]  # the owner's 3:1 example: the extra deal is a Wholesale
    assert spread(5, [0, 0]) == [3, 2] and spread(0, [4, 12]) == [0, 0]


def test_editing_an_exit_row_sets_the_source(ds, p):
    from projection.plan import edit_exit

    bb = backbone(ds, p, Q4)
    i = next(i for i, r in enumerate(p.revenue) if (r.source, r.exit) == ("PPC A", "Wholesale"))
    edit_exit(p, i, bb, S, deals=15.6)  # 16 whole
    a = rows(ds, p)["PPC A"]
    assert p.drivers["PPC A"].kind == "exits" and (a.deals, a.spend) == (22, 33000)


def test_manual_source_types_all_three(ds, p):
    from projection.plan import edit_exit, set_manual

    bb = backbone(ds, p, Q4)
    set_manual(p, "Mailer C", bb, S, spend=10000, deals=4, revenue=60000)
    m = rows(ds, p)["Mailer C"]
    assert (m.spend, m.deals, m.revenue) == (10000, 4, 60000) and m.unallocated == 4  # no exit rows yet
    from projection.planning import add_revenue_line

    p = add_revenue_line(p, "main", "Mailer C", "Wholesale")
    set_manual(p, "Mailer C", bb, S, deals=4)
    line = next(r for r in p.revenue if r.source == "Mailer C")
    assert (line.p_deals, line.p_avg) == (4, 15000)  # avg deal = revenue ÷ deals
    edit_exit(p, p.revenue.index(line), bb, S, deals=5)
    m = rows(ds, p)["Mailer C"]
    assert (m.deals, m.revenue, m.spend) == (5, 75000, 10000)
    assert next(c for c in p.marketing if c.source == "Mailer C").p_cost == 10000


def test_revenue_and_deals_drivers_work_back_the_spend(ds, p):
    bb = backbone(ds, p, Q4)
    set_driver(p, "PPC A", "revenue", 172500, bb, S)
    a = rows(ds, p)["PPC A"]
    assert (a.deals, a.spend) == (10, 15000)
    set_driver(p, "PPC A", "deals", 25, bb, S)
    assert rows(ds, p)["PPC A"].spend == 37500  # the required 25 × $1,500 case
    set_driver(p, FOLLOW_UP, "deals", 3, bb, S)
    fu = rows(ds, p)[FOLLOW_UP]
    assert (fu.deals, fu.revenue, fu.unallocated, fu.spend) == (3, 90000, 0, 0)
    assert {r.exit: r.p_deals for r in p.revenue if r.source == FOLLOW_UP} == {"Fix & Flip": 3}
    assert totals(p, source_rows(p, bb, S))["not_placed"] == 0


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


def test_active_list_decides_own_rows_and_follow_up(ds):
    s = {**DEFAULT_SETTINGS, "active_sources": ["SEO B", "PPC A", "Brand New"]}
    p = prefill(ds, Q4, s, QuarterProjection(quarter_id="2026-Q4"))
    assert [c.source for c in p.marketing] == ["SEO B", "PPC A", "Brand New"]  # the list's order, even with no data
    fu = {r.exit: r.p_deals for r in p.revenue if r.source == FOLLOW_UP}
    assert fu == {"Fix & Flip": 1, "Retail Listing": 1, "Wholesale": 1}  # SELF GEN is not active here: Follow Up
    assert "Mailer C" not in {c.source for c in p.marketing}  # spend off the list is not projected
    codes = {i.code: i for i in build_dataset(mf.raw_sheet(), s, today=mf.TODAY).issues}
    assert codes["active_not_found"].examples == ["Brand New"]
    assert codes["spend_not_active"].examples == ["Mailer C: $2,000"]


def test_old_save_keeps_its_spend_and_missing_active_sources_can_be_added(ds):
    from projection.model import CostLine
    from projection.plan import add_active_sources

    old = QuarterProjection(quarter_id="2026-Q4", marketing=[CostLine(source="SEO B", p_cost=4000),
                                                             CostLine(source="Hand Typed")])
    r = rows(ds, old)
    # no drivers saved: its spend is the driver (1.33 deals -> 1 whole deal at $3,000)
    assert r["SEO B"].spend == 3000 and r["SEO B"].deals == 1 and r["SEO B"].driver.kind == "spend"
    added = add_active_sources(old, ds, Q4, S)
    assert added == ["PPC A", "Mailer C", "SELF GEN"]
    assert [c.source for c in old.marketing] == ["PPC A", "SEO B", "Mailer C", "SELF GEN", "Hand Typed"]
    assert next(c for c in old.marketing if c.source == "SEO B").p_cost == 3000  # 1 whole deal
    assert next(c for c in old.marketing if c.source == "PPC A").p_cost == 30000


def test_reorder_moves_sources_and_their_exit_rows(ds, p):
    from projection.plan import reorder

    reorder(p, ["SELF GEN", "PPC A"])
    assert [c.source for c in p.marketing] == ["SELF GEN", "PPC A", "SEO B", "Mailer C"]  # the rest keep their place
    assert [r.source for r in p.revenue] == ["SELF GEN"] * 2 + ["PPC A"] * 3 + ["SEO B", FOLLOW_UP]
    assert DEFAULT_SETTINGS["active_sources"][:3] == ["PPC NW RDS", "PPC NW SM3", "SEO HESEL (WEBUYSOUTHFL.COM)"]
    assert DEFAULT_SETTINGS["active_sources"][-1] == "PPC FL RDS"
