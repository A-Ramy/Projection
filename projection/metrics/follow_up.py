"""Revenue actuals laid onto a quarter projection's rows, with the Follow Up roll-up per block.

For each REVENUES row in the period (block = its exit strategy's block):
  - its Source has no row in that block of the projection  -> the block's Follow Up row for that exit
  - its Source × Exit has a projected row                  -> that row
  - its Source is projected in the block, but not this exit -> an auto "(unprojected)" actual-only row
So the lines always add up to all revenue in the period.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

import pandas as pd

from projection.data.load import Dataset
from projection.data.schema import block_of
from projection.metrics.core import in_months, ratio
from projection.model import BLOCKS, FOLLOW_UP, QuarterProjection
from projection.periods import Month

PROJECTED, UNPROJECTED, FOLLOW_UP_KIND = "projected", "unprojected", "follow_up"


@dataclass
class RevenueActual:
    block: str
    source: str
    exit: str
    kind: str  # projected | unprojected | follow_up
    p_deals: float = 0.0
    p_revenue: float = 0.0
    a_deals: int = 0
    a_revenue: float = 0.0
    contributors: dict[str, list[float]] = field(default_factory=dict)  # Follow Up drill-down: src -> [deals, rev]

    @property
    def label(self) -> str:
        return f"{self.source} (unprojected)" if self.kind == UNPROJECTED else self.source

    @property
    def p_avg(self) -> float | None:
        return ratio(self.p_revenue, self.p_deals)

    @property
    def a_avg(self) -> float | None:
        return ratio(self.a_revenue, self.a_deals)

    @property
    def pva_deals(self) -> float:
        return self.a_deals - self.p_deals

    @property
    def pva_revenue(self) -> float:
        return self.a_revenue - self.p_revenue


def revenue_actuals(ds: Dataset, projection: QuarterProjection, months: Iterable[Month]) -> list[RevenueActual]:
    lines: dict[tuple[str, str, str], RevenueActual] = {}
    for r in projection.revenue:
        kind = FOLLOW_UP_KIND if r.source == FOLLOW_UP else PROJECTED
        line = lines.setdefault((r.block, r.source, r.exit), RevenueActual(r.block, r.source, r.exit, kind))
        line.p_deals += r.p_deals
        line.p_revenue += r.p_revenue
    named = {b: projection.sources_in_block(b) for b in BLOCKS}

    for row in in_months(ds.revenues, months).itertuples():
        block = block_of(row.exit)
        if row.source not in named[block]:
            key, kind = (block, FOLLOW_UP, row.exit), FOLLOW_UP_KIND
        else:
            key = (block, row.source, row.exit)
            kind = PROJECTED if key in lines else UNPROJECTED
        line = lines.setdefault(key, RevenueActual(*key, kind))
        line.a_deals += 1
        line.a_revenue += row.revenue
        if kind == FOLLOW_UP_KIND:
            c = line.contributors.setdefault(row.source, [0, 0.0])
            c[0] += 1
            c[1] += row.revenue

    order = {b: i for i, b in enumerate(BLOCKS)}
    kind_order = {PROJECTED: 0, UNPROJECTED: 1, FOLLOW_UP_KIND: 2}
    return sorted(lines.values(), key=lambda x: (order.get(x.block, 9), kind_order[x.kind]))


def to_frame(lines: list[RevenueActual]) -> pd.DataFrame:
    return pd.DataFrame([{
        "block": x.block, "source": x.label, "exit": x.exit, "kind": x.kind,
        "p_deals": x.p_deals, "p_avg": x.p_avg, "p_revenue": x.p_revenue,
        "a_deals": x.a_deals, "a_avg": x.a_avg, "a_revenue": x.a_revenue,
        "pva_deals": x.pva_deals, "pva_revenue": x.pva_revenue,
    } for x in lines])
