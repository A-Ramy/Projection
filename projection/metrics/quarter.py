"""One quarter's projection vs actuals: cost lines, revenue lines, P.% / A.%, profit and margin.

Costs are posted as month totals, so actual costs cover only the quarter's cost-complete months, and
every cost comparison (A.%, profit) uses revenue from those same months. Revenue lines run to today.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from projection.data.load import Dataset
from projection.metrics.core import complete_in, in_months, marketing_names, pct_base, ratio
from projection.metrics.follow_up import RevenueActual, revenue_actuals
from projection.model import QuarterProjection
from projection.periods import Month, Period

MARKETING, NON_MARKETING, OTHER_MARKETING = "marketing", "non_marketing", "other_marketing"
OTHER_MARKETING_LABEL = "Other marketing (unprojected)"


@dataclass
class CostActual:
    source: str
    kind: str  # marketing | non_marketing | other_marketing
    p_cost: float
    a_cost: float
    p_pct: float | None = None
    a_pct: float | None = None
    contributors: dict[str, float] = field(default_factory=dict)  # Other marketing breakdown

    @property
    def pva_cost(self) -> float:
        """P − A: ≥ 0 is under budget (green), < 0 over (red)."""
        return self.p_cost - self.a_cost

    @property
    def pva_pct(self) -> float | None:
        return None if self.p_pct is None or self.a_pct is None else self.p_pct - self.a_pct


@dataclass
class QuarterView:
    period: Period
    cost_months: list[Month]  # the quarter's cost-complete months
    costs: list[CostActual]
    revenue: list[RevenueActual]  # to today
    p_base: float  # projected revenue base for P.%
    a_base: float  # actual revenue base for A.%, same months as the costs
    a_revenue_cost_months: float  # all actual revenue in the cost-complete months

    @property
    def complete(self) -> bool:
        return len(self.cost_months) == len(self.period.months)

    @property
    def costs_label(self) -> str:
        if self.complete:
            return "costs for the full quarter"
        if not self.cost_months:
            return "no cost month complete yet"
        return f"costs through {self.cost_months[-1].label}"

    @property
    def p_cost(self) -> float:
        return sum(c.p_cost for c in self.costs)

    @property
    def a_cost(self) -> float:
        return sum(c.a_cost for c in self.costs)

    @property
    def p_revenue(self) -> float:
        return sum(r.p_revenue for r in self.revenue)

    @property
    def a_revenue(self) -> float:
        return sum(r.a_revenue for r in self.revenue)

    @property
    def p_profit(self) -> float:
        return self.p_revenue - self.p_cost

    @property
    def a_profit(self) -> float:
        """Revenue − cost over the cost-complete months (labelled with costs_label)."""
        return self.a_revenue_cost_months - self.a_cost

    @property
    def p_margin(self) -> float | None:
        return ratio(self.p_profit, self.p_revenue)

    @property
    def a_margin(self) -> float | None:
        return ratio(self.a_profit, self.a_revenue_cost_months)

    @property
    def p_pct(self) -> float | None:
        return ratio(self.p_cost, self.p_base)

    @property
    def a_pct(self) -> float | None:
        return ratio(self.a_cost, self.a_base)


def quarter_view(ds: Dataset, projection: QuarterProjection, period: Period, settings: dict) -> QuarterView:
    cost_months = complete_in(period, ds)
    excluded = set(settings.get("pct_base_excluded_exits", []))
    p_base = sum(r.p_revenue for r in projection.revenue if r.exit not in excluded)
    a_base = pct_base(ds, cost_months, settings)

    actual = in_months(ds.costs, cost_months).groupby("source")["cost"].sum()
    mkt = marketing_names(ds, settings)
    lines: list[CostActual] = []
    seen: set[str] = set()
    for kind, group in ((MARKETING, projection.marketing), (NON_MARKETING, projection.non_marketing)):
        for c in group:
            lines.append(CostActual(c.source, kind, c.p_cost, float(actual.get(c.source, 0.0))))
            seen.add(c.source)
    other = {s: float(v) for s, v in actual.items() if s in mkt and s not in seen}
    lines.append(CostActual(OTHER_MARKETING_LABEL, OTHER_MARKETING, 0.0, sum(other.values()), contributors=other))
    unseen_non = {s: float(v) for s, v in actual.items() if s not in mkt and s not in seen}
    for s, v in unseen_non.items():  # a non-marketing line left off the projection still counts
        lines.append(CostActual(s, NON_MARKETING, 0.0, v))
    for c in lines:
        c.p_pct, c.a_pct = ratio(c.p_cost, p_base), ratio(c.a_cost, a_base)

    return QuarterView(
        period=period, cost_months=cost_months, costs=lines,
        revenue=revenue_actuals(ds, projection, period.months),
        p_base=p_base, a_base=a_base,
        a_revenue_cost_months=float(in_months(ds.revenues, cost_months)["revenue"].sum()),
    )
