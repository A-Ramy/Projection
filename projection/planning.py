"""Projections tab logic (no Streamlit): quarters to pick from, starting a draft, the tables shown, and the
reconciliation check that the lines add up to the sheet."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from projection.data.load import Dataset
from projection.data.schema import block_of
from projection.metrics.core import in_months, marketing_names
from projection.metrics.follow_up import UNPROJECTED, to_frame
from projection.metrics.quarter import OTHER_MARKETING, QuarterView
from projection.model import BLOCKS, FOLLOW_UP, CostLine, QuarterProjection, RevenueLine
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


def copy_lines(prev: QuarterProjection, quarter_id: str) -> QuarterProjection:
    """The previous quarter's lines and values, as a starting point (origins reset to manual)."""
    data = prev.model_dump()
    data["quarter_id"] = quarter_id
    for group in ("marketing", "non_marketing", "revenue"):
        for line in data[group]:
            line["origin"], line["inputs"] = "manual", None
    return QuarterProjection.model_validate(data)


def add_actual_lines(p: QuarterProjection, ds: Dataset, period: Period, settings: dict) -> QuarterProjection:
    """Add a line (with P = 0) for every marketing source with spend and every Source × Exit with deals in the
    quarter that isn't on the projection yet. Used to backfill past quarters."""
    p = p.model_copy(deep=True)
    have = {c.source for c in p.marketing + p.non_marketing}
    costs = in_months(ds.costs, period.months)
    mkt = marketing_names(ds, settings)
    for src in sorted(costs["source"].unique()):
        if src not in have:
            (p.marketing if src in mkt else p.non_marketing).append(CostLine(source=src))
    rows = {(r.block, r.source, r.exit) for r in p.revenue}
    revs = in_months(ds.revenues, period.months)
    for src, exit_ in sorted(set(zip(revs["source"], revs["exit"], strict=True))):
        key = (block_of(exit_), src, exit_)
        if key not in rows:
            p.revenue.append(RevenueLine(block=key[0], source=src, exit=exit_))
            rows.add(key)
    return p


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


# ---------- tables
COST_COLUMNS = ["source", "kind", "p_cost", "a_cost", "pva_cost", "p_pct", "a_pct", "pva_pct"]


def cost_table(view: QuarterView) -> pd.DataFrame:
    rows = [{"source": c.source, "kind": c.kind, "p_cost": c.p_cost, "a_cost": c.a_cost, "pva_cost": c.pva_cost,
             "p_pct": c.p_pct, "a_pct": c.a_pct, "pva_pct": c.pva_pct} for c in view.costs]
    return pd.DataFrame(rows, columns=COST_COLUMNS)


def revenue_table(view: QuarterView, block: str) -> pd.DataFrame:
    df = to_frame([x for x in view.revenue if x.block == block])
    return df if len(df) else pd.DataFrame(columns=["block", "source", "exit", "kind", "p_deals", "p_avg",
                                                     "p_revenue", "a_deals", "a_avg", "a_revenue", "pva_deals",
                                                     "pva_revenue"])


def other_marketing(view: QuarterView) -> dict[str, float]:
    return next((c.contributors for c in view.costs if c.kind == OTHER_MARKETING), {})


def follow_up_sources(view: QuarterView, block: str) -> pd.DataFrame:
    rows = [{"exit": x.exit, "source": s, "deals": d, "revenue": r}
            for x in view.revenue if x.block == block and x.source == FOLLOW_UP
            for s, (d, r) in x.contributors.items()]
    return pd.DataFrame(rows, columns=["exit", "source", "deals", "revenue"])


def unprojected_count(view: QuarterView) -> int:
    return sum(1 for x in view.revenue if x.kind == UNPROJECTED)


def monthly_costs(ds: Dataset, period: Period) -> pd.DataFrame:
    """Actual cost per source × month (columns = month labels, plus Total)."""
    c = in_months(ds.costs, period.months)
    t = c.pivot_table(index="source", columns="month", values="cost", aggfunc="sum", fill_value=0.0)
    t = t.reindex(columns=period.month_keys, fill_value=0.0)
    t.columns = [Month.from_key(k).label for k in t.columns]
    t["Total"] = t.sum(axis=1)
    return t.sort_values("Total", ascending=False)


def monthly_revenue(ds: Dataset, period: Period) -> pd.DataFrame:
    """Actual deals and revenue per block × month."""
    r = in_months(ds.revenues, period.months)
    r = r.assign(block=r["exit"].map(block_of).map(BLOCK_LABELS))
    rows = []
    for b in BLOCKS:
        label = BLOCK_LABELS[b]
        g = r[r["block"] == label]
        row = {"block": label}
        for m in period.months:
            gm = g[g["month"] == m.key]
            row[f"{m.label} deals"], row[f"{m.label} revenue"] = len(gm), float(gm["revenue"].sum())
        row["Total deals"], row["Total revenue"] = len(g), float(g["revenue"].sum())
        rows.append(row)
    return pd.DataFrame(rows).set_index("block")


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
