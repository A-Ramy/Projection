"""Projections tab helpers (no Streamlit): quarters to pick from, a blank quarter, adding lines, the single-month
view, and the check that the actuals add up to the sheet. Building a quarter from its backbone: projection/plan.py."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from projection.data.load import Dataset
from projection.metrics.core import in_months
from projection.metrics.quarter import QuarterView
from projection.model import CostLine, QuarterProjection, RevenueLine
from projection.periods import Month, Period, month_range, parse_period_key, period_of

BLOCK_LABELS = {"main": "Revenue", "fix_flip": "Fix & Flip", "buy_hold": "Buy & Hold"}


def quarter_options(start: date, today: date) -> list[Period]:
    """Every quarter from the start date's quarter through next quarter (for planning ahead)."""
    first, last = period_of(Month.of(start), "quarter"), period_of(Month.of(today).add(3), "quarter")
    return [period_of(m, "quarter") for m in month_range(first.months[0], last.months[0])
            if m.month in (1, 4, 7, 10)]


def previous_quarter(quarter_id: str) -> str:
    return period_of(parse_period_key(quarter_id).months[0].add(-3), "quarter").key


def new_projection(quarter_id: str, settings: dict) -> QuarterProjection:
    """A blank quarter: the non-marketing lines (always present) and nothing else. Sources are chosen, never
    added silently."""
    return QuarterProjection(quarter_id=quarter_id,
                             non_marketing=[CostLine(source=s) for s in settings.get("non_marketing", [])],
                             lookback=settings.get("lookback_default", "last_quarter"))


def add_source(p: QuarterProjection, source: str, marketing: bool = True) -> QuarterProjection:
    p = p.model_copy(deep=True)
    if source and source not in {c.source for c in p.marketing + p.non_marketing}:
        (p.marketing if marketing else p.non_marketing).append(CostLine(source=source))
    return p


def add_revenue_line(p: QuarterProjection, block: str, source: str, exit_: str) -> QuarterProjection:
    p = p.model_copy(deep=True)
    if source and exit_ and (block, source, exit_) not in {(r.block, r.source, r.exit) for r in p.revenue}:
        p.revenue.append(RevenueLine(block=block, source=source, exit=exit_))
    return p


def scale_projection(p: QuarterProjection, factor: float) -> QuarterProjection:
    """The projection's values × factor (a single month of a quarter = ÷ 3)."""
    p = p.model_copy(deep=True)
    for c in p.marketing + p.non_marketing:
        c.p_cost *= factor
    for r in p.revenue:
        r.p_deals *= factor
    return p


# ---------- reconciliation
@dataclass(frozen=True)
class Reconciliation:
    sheet_cost: float  # Σ COSTS in the quarter's cost-complete months
    lines_cost: float  # Σ actual cost lines
    sheet_revenue: float  # Σ REVENUES in the quarter
    lines_revenue: float
    sheet_deals: int
    lines_deals: int

    @property
    def ok(self) -> bool:
        return (abs(self.sheet_cost - self.lines_cost) < 0.005 and abs(self.sheet_revenue - self.lines_revenue) < 0.005
                and self.sheet_deals == self.lines_deals)


def reconcile(ds: Dataset, view: QuarterView) -> Reconciliation:
    revs = in_months(ds.revenues, view.period.months)
    return Reconciliation(
        sheet_cost=float(in_months(ds.costs, view.cost_months)["cost"].sum()), lines_cost=view.a_cost,
        sheet_revenue=float(revs["revenue"].sum()), lines_revenue=view.a_revenue,
        sheet_deals=len(revs), lines_deals=sum(x.a_deals for x in view.revenue))
