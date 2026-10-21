"""Projections tab helpers: quarters, a blank quarter, adding lines, scaling, and reconciliation to the sheet."""

from datetime import date

import pytest

from projection.config import DEFAULT_SETTINGS
from projection.data.load import build_dataset
from projection.metrics.quarter import quarter_view
from projection.model import Driver, QuarterProjection
from projection.periods import quarter
from projection.planning import (
    add_revenue_line,
    add_source,
    new_projection,
    previous_quarter,
    quarter_options,
    reconcile,
    scale_projection,
)
from projection.storage import Store
from tests import metrics_fixture as mf

S = DEFAULT_SETTINGS
Q3 = quarter(2026, 3)


@pytest.fixture(scope="module")
def ds():
    return build_dataset(mf.raw_sheet(), S, today=mf.TODAY)


def test_quarter_options_start_to_next_quarter():
    opts = quarter_options(date(2026, 1, 1), date(2026, 10, 18))
    assert [p.key for p in opts] == ["2026-Q1", "2026-Q2", "2026-Q3", "2026-Q4", "2027-Q1"]
    assert previous_quarter("2026-Q1") == "2025-Q4"


def test_new_projection_has_only_non_marketing_lines():
    p = new_projection("2026-Q4", S)
    assert p.marketing == [] and p.revenue == [] and p.drivers == {}
    assert [c.source for c in p.non_marketing] == S["non_marketing"]


def test_empty_projection_still_reconciles(ds):
    v = quarter_view(ds, new_projection("2026-Q3", S), Q3, S)
    r = reconcile(ds, v)
    assert r.ok and r.sheet_cost == 95000 and r.sheet_revenue == 415000 and r.sheet_deals == 24


def test_add_lines_without_duplicates_and_scale():
    p = add_source(new_projection("2026-Q3", S), "PPC A")
    p = add_source(p, "PPC A")
    p = add_revenue_line(add_revenue_line(p, "main", "PPC A", "Wholesale"), "main", "PPC A", "Wholesale")
    assert [c.source for c in p.marketing] == ["PPC A"] and len(p.revenue) == 1
    p.marketing[0].p_cost, p.revenue[0].p_deals = 30000, 6
    m = scale_projection(p, 1 / 3)
    assert (m.marketing[0].p_cost, m.revenue[0].p_deals) == (10000, 2) and p.marketing[0].p_cost == 30000


def test_projection_round_trips_through_storage(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 't.db'}")
    p = add_revenue_line(add_source(new_projection("2026-Q4", S), "PPC A"), "main", "PPC A", "Wholesale")
    p.drivers["PPC A"] = Driver(kind="spend", value=45000)
    store.save_revision(p.quarter_id, p.model_dump(), by="owner", note="first")
    back = QuarterProjection.model_validate(store.latest_revision("2026-Q4")["payload"])
    assert back == p and back.drivers["PPC A"].kind == "spend"


def test_saved_novation_deal_rows_load_as_novation():
    from projection.model import RevenueLine

    assert RevenueLine(block="main", source="PPC A", exit="Novation Deal").exit == "Novation"
