"""ROAS overall, per source and per exit (tests/metrics_fixture.py; Q4 2026 built on Q3 2026)."""

from projection.config import DEFAULT_SETTINGS
from projection.data.load import build_dataset
from projection.metrics import roas
from projection.model import FOLLOW_UP, QuarterProjection
from projection.periods import quarter
from projection.plan import backbone, prefill, source_rows
from tests import metrics_fixture as mf

S = {**DEFAULT_SETTINGS, "active_sources": ["PPC A", "SEO B", "Mailer C", "SELF GEN"]}


def test_projected_and_actual_roas_add_up():
    ds = build_dataset(mf.raw_sheet(), S, today=mf.TODAY)
    p = prefill(ds, quarter(2026, 4), S, QuarterProjection(quarter_id="2026-Q4"))
    pr = roas.projected(p, source_rows(p, backbone(ds, p, quarter(2026, 4)), S))
    assert (pr.spend, pr.revenue) == (35000, 415000) and abs(pr.roas - 415000 / 35000) < 1e-9
    a = next(x for x in pr.sources if x.source == "PPC A")
    assert (a.spend, a.revenue, a.roas) == (30000, 345000, 11.5)
    nov = next(x for x in pr.exits if (x.source, x.exit) == ("PPC A", "Novation Deal"))
    assert nov.spend == 4 * 1500 and abs(nov.roas - 25000 / 1500) < 1e-9  # avg deal ÷ cost per deal
    assert next(x for x in pr.sources if x.source == "SELF GEN").roas is None  # no spend

    q3 = list(quarter(2026, 3).months)
    ac = roas.actual(ds, p, q3, S)
    assert (ac.spend, ac.revenue) == (35000, 415000)
    assert sum(x.spend or 0 for x in ac.sources) == ac.spend and sum(x.revenue for x in ac.sources) == ac.revenue
    assert next(x for x in ac.sources if x.source == FOLLOW_UP).revenue == 30000  # Inbound X
    ppc = [x for x in ac.exits if x.source == "PPC A"]
    assert abs(sum(x.spend for x in ppc) - 30000) < 1e-6
