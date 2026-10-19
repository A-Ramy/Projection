"""ROAS (return on ad spend) = revenue ÷ marketing spend, overall, per source and per exit, projected and actual.

Per exit, a source's spend is shared over its exits by deals (each deal costs the source's cost per deal), so an
exit's ROAS = its revenue ÷ (its deals × the source's cost per deal) = its avg deal ÷ cost per deal.
Actuals use the cost-complete months only (revenue from the same months), so revenue and spend line up.
Sources not on the projection are grouped as Follow Up, as everywhere else (in actuals their spend too, so the source
lines add up to the overall spend).
"""

from __future__ import annotations

from dataclasses import dataclass

from projection.data.load import Dataset
from projection.metrics.core import in_months, marketing_names, ratio
from projection.model import FOLLOW_UP, QuarterProjection
from projection.periods import Month


@dataclass(frozen=True)
class RoasLine:
    source: str
    exit: str  # "" on a source line
    deals: float
    revenue: float
    spend: float | None  # None: no marketing spend (no-cost sources, Follow Up)

    @property
    def roas(self) -> float | None:
        return ratio(self.revenue, self.spend) if self.spend else None


@dataclass(frozen=True)
class Roas:
    spend: float
    revenue: float
    sources: list[RoasLine]
    exits: list[RoasLine]

    @property
    def roas(self) -> float | None:
        return ratio(self.revenue, self.spend)


def _exits(source: str, spend: float | None, deals: float, by_exit: list[tuple[str, float, float]]) -> list[RoasLine]:
    cpd = spend / deals if spend and deals else None
    return [RoasLine(source, e, d, r, d * cpd if cpd is not None else None) for e, d, r in by_exit]


def projected(p: QuarterProjection, rows) -> Roas:
    """From the projection's source rows (plan.source_rows) and exit rows."""
    sources, exits = [], []
    for r in rows:
        spend = None if r.kind == "follow_up" else (r.spend or None)
        deals = r.deals if r.deals is not None else r.allocated_deals
        revenue = r.revenue if r.revenue is not None else r.allocated_revenue
        sources.append(RoasLine(r.source, "", deals, revenue, spend))
        lines = [(x.exit, x.p_deals, x.p_revenue) for x in p.revenue if x.source == r.source]
        exits += _exits(r.source, spend, sum(d for _, d, _ in lines), lines)
    spend = sum(s.spend or 0 for s in sources)
    return Roas(spend, sum(s.revenue for s in sources), sources, exits)


def actual(ds: Dataset, p: QuarterProjection, months: list[Month], settings: dict) -> Roas:
    """Actual spend and revenue over the given (cost-complete) months."""
    costs, revs = in_months(ds.costs, months), in_months(ds.revenues, months)
    mkt = marketing_names(ds, settings)
    costs = costs[costs["source"].isin(mkt)]
    on = [c.source for c in p.marketing]
    group = lambda s: s if s in p.projected_sources() else FOLLOW_UP  # noqa: E731
    revs = revs.assign(group=revs["source"].map(group))
    spent = costs.groupby(costs["source"].map(group))["cost"].sum()  # spend off the projection counts as Follow Up
    order = on + [s for s in sorted(set(revs["group"])) if s not in on and s != FOLLOW_UP] + [FOLLOW_UP]
    sources, exits = [], []
    for src in order:
        g = revs[revs["group"] == src]
        spend = float(spent.get(src, 0.0))
        if g.empty and not spend:
            continue
        sources.append(RoasLine(src, "", len(g), float(g["revenue"].sum()), spend or None))
        by_exit = [(e or "(no exit)", len(x), float(x["revenue"].sum())) for e, x in g.groupby("exit")]
        exits += _exits(src, spend or None, len(g), by_exit)
    return Roas(float(costs["cost"].sum()), float(revs["revenue"].sum()), sources, exits)
