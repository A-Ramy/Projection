"""Projections tab logic: quarters, starting a draft, tables and the reconciliation to the sheet."""

from datetime import date

import pytest

from projection.config import DEFAULT_SETTINGS
from projection.data.load import build_dataset
from projection.metrics.quarter import quarter_view
from projection.model import FOLLOW_UP, CostLine, QuarterProjection, RevenueLine
from projection.periods import quarter
from projection.planning import (
    add_actual_lines,
    add_revenue_line,
    add_source,
    copy_lines,
    cost_table,
    follow_up_sources,
    monthly_costs,
    monthly_revenue,
    new_projection,
    previous_quarter,
    quarter_options,
    reconcile,
    revenue_table,
)
from projection.storage import Store
from tests import metrics_fixture as mf

S = DEFAULT_SETTINGS
Q3, Q4 = quarter(2026, 3), quarter(2026, 4)


@pytest.fixture(scope="module")
def ds():
    return build_dataset(mf.raw_sheet(), S, today=mf.TODAY)


def test_quarter_options_start_to_next_quarter():
    opts = quarter_options(date(2026, 1, 1), date(2026, 10, 18))
    assert [p.key for p in opts] == ["2026-Q1", "2026-Q2", "2026-Q3", "2026-Q4", "2027-Q1"]
    assert previous_quarter("2026-Q1") == "2025-Q4"


def test_new_projection_has_only_non_marketing_lines():
    p = new_projection("2026-Q4", S)
    assert p.marketing == [] and p.revenue == []
    assert [c.source for c in p.non_marketing] == S["non_marketing"]


def test_empty_projection_still_reconciles(ds):
    v = quarter_view(ds, new_projection("2026-Q3", S), Q3, S)
    r = reconcile(ds, v)
    assert r.ok and r.sheet_cost == 95000 and r.sheet_revenue == 415000 and r.sheet_deals == 24
    lines = {c.source: c.a_cost for c in v.costs}
    assert lines["Other marketing (unprojected)"] == 35000 and lines["ACQ Payroll"] == 60000
    fu = follow_up_sources(v, "main")  # with nothing projected, every deal is Follow Up
    assert fu["deals"].sum() + follow_up_sources(v, "fix_flip")["deals"].sum() == 24


def test_add_actual_lines_backfills_a_past_quarter(ds):
    p = add_actual_lines(new_projection("2026-Q3", S), ds, Q3, S)
    assert [c.source for c in p.marketing] == ["Mailer C", "PPC A", "SEO B"]
    keys = {(r.block, r.source, r.exit) for r in p.revenue}
    assert ("main", "PPC A", "Novation Deal") in keys and ("fix_flip", "PPC A", "Fix & Flip") in keys
    assert ("fix_flip", "Inbound X", "Fix & Flip") in keys and len(keys) == 7
    v = quarter_view(ds, p, Q3, S)
    assert reconcile(ds, v).ok
    assert {x.kind for x in v.revenue} == {"projected"}  # every actual now sits on its own line
    assert add_actual_lines(p, ds, Q3, S) == p  # idempotent


def test_add_and_copy_lines():
    p = add_source(new_projection("2026-Q3", S), "PPC A")
    p = add_source(p, "PPC A")  # no duplicates
    p = add_revenue_line(p, "main", "PPC A", "Wholesale")
    p.marketing[0].p_cost, p.marketing[0].origin = 30000, "accepted_suggestion"
    q = copy_lines(p, "2026-Q4")
    assert q.quarter_id == "2026-Q4" and q.marketing[0].p_cost == 30000 and q.marketing[0].origin == "manual"
    assert [(r.source, r.exit) for r in q.revenue] == [("PPC A", "Wholesale")]
    assert p.marketing[0].origin == "accepted_suggestion"  # the original is untouched


def test_tables_and_monthly_breakdown(ds):
    p = QuarterProjection(quarter_id="2026-Q3", marketing=[CostLine(source="PPC A", p_cost=28000)],
                          revenue=[RevenueLine(block="main", source="PPC A", exit="Wholesale", p_deals=12,
                                               p_avg=15000),
                                   RevenueLine(block="main", source=FOLLOW_UP, exit="Wholesale", p_deals=1,
                                               p_avg=15000)])
    v = quarter_view(ds, p, Q3, S)
    ct = cost_table(v).set_index("source")
    assert ct.loc["PPC A", "pva_cost"] == -2000 and ct.loc["ACQ Payroll", "a_cost"] == 60000
    rt = revenue_table(v, "main").set_index(["source", "exit"])
    assert rt.loc[("PPC A (unprojected)", "Novation Deal"), "a_revenue"] == 100000
    assert revenue_table(v, "buy_hold").empty
    mc = monthly_costs(ds, Q3)
    assert list(mc.columns) == ["Jul 2026", "Aug 2026", "Sep 2026", "Total"]
    assert mc.loc["PPC A", "Total"] == 30000 and mc.loc["Mailer C", "Aug 2026"] == 2000
    mr = monthly_revenue(ds, Q3)
    assert mr.loc["Revenue", "Total revenue"] == 350000 and mr.loc["Fix & Flip", "Total deals"] == 3
    assert mr.loc["Revenue", "Aug 2026 deals"] == 11  # 10 PPC A + 1 SELF GEN


def test_projection_round_trips_through_storage(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 't.db'}")
    p = add_revenue_line(add_source(new_projection("2026-Q4", S), "PPC A"), "main", "PPC A", "Wholesale")
    store.save_revision(p.quarter_id, p.model_dump(), by="owner", note="first")
    back = QuarterProjection.model_validate(store.latest_revision("2026-Q4")["payload"])
    assert back == p
