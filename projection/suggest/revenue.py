"""D2: suggested P.Deals and P.Avg per revenue row, from the lookback window.

    P.Deals = deals in the window / quarters in the window;  P.Avg = window revenue / window deals
A Follow Up row uses the pooled history of the sources that would roll into it: those not on the projection.
"""

from __future__ import annotations

from dataclasses import dataclass

from projection.data.load import Dataset
from projection.data.schema import block_of
from projection.metrics.core import in_months, ratio
from projection.model import FOLLOW_UP, QuarterProjection
from projection.periods import Month


@dataclass(frozen=True)
class RevenueSuggestion:
    block: str
    source: str
    exit: str
    deals: int  # window inputs
    revenue: float
    quarters: float
    sources: tuple[str, ...]  # history used (the pooled sources for Follow Up)

    @property
    def p_deals(self) -> float | None:
        return ratio(self.deals, self.quarters)

    @property
    def p_avg(self) -> float | None:
        return ratio(self.revenue, self.deals)

    @property
    def p_revenue(self) -> float | None:
        return None if self.p_deals is None or self.p_avg is None else self.p_deals * self.p_avg


def suggest_revenue(ds: Dataset, projection: QuarterProjection, months: list[Month]) -> list[RevenueSuggestion]:
    r = in_months(ds.revenues, months)
    r = r.assign(block=r["exit"].map(block_of))
    quarters = len(months) / 3
    out = []
    for line in projection.revenue:
        rows = r[(r["block"] == line.block) & (r["exit"] == line.exit)]
        if line.source == FOLLOW_UP:
            rows = rows[~rows["source"].isin(projection.projected_sources())]
        else:
            rows = rows[rows["source"] == line.source]
        out.append(RevenueSuggestion(line.block, line.source, line.exit, len(rows), float(rows["revenue"].sum()),
                                     quarters, tuple(sorted(rows["source"].unique()))))
    return out
