"""D3: reverse-engineer marketing-source deals from a profit target.

Fixed: non-marketing costs (projected), and the projected revenue of Follow Up, Fix & Flip and Buy & Hold.
    needed contribution = target profit + fixed costs − fixed revenue
    a source's contribution per deal = avg main-block deal size − cost per deal
Plan A fills the need from the lowest cost per deal (with positive contribution) up to each source's cap
(scale_cap × best quarter spend ÷ cost per deal), then the next source. Plan B scales every projected
source's main-block deals by one factor k. Both show deals and budget per source, and any shortfall.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from projection.data.load import Dataset
from projection.data.schema import block_of
from projection.metrics.core import by_source, cost_complete_months, in_months, ratio
from projection.model import FOLLOW_UP, QuarterProjection
from projection.periods import Month
from projection.suggest.guardrails import best_quarter_spend

EPS = 1e-9


@dataclass(frozen=True)
class SourceEconomics:
    source: str
    cost_per_deal: float | None
    avg_deal: float | None  # main block
    projected_deals: float  # main block P.Deals
    best_quarter: float
    scale_cap: float = 1.5

    @property
    def contribution(self) -> float | None:
        if self.cost_per_deal is None or self.avg_deal is None:
            return None
        return self.avg_deal - self.cost_per_deal

    @property
    def max_deals(self) -> float:
        if not self.cost_per_deal:
            return 0.0
        return self.scale_cap * self.best_quarter / self.cost_per_deal


@dataclass
class PlanLine:
    source: str
    deals: float
    budget: float
    contribution: float
    over_cap: bool = False


@dataclass
class Plan:
    name: str
    needed: float
    lines: list[PlanLine] = field(default_factory=list)
    k: float | None = None  # Plan B factor

    @property
    def achieved(self) -> float:
        return sum(x.contribution for x in self.lines)

    @property
    def shortfall(self) -> float:
        return max(0.0, self.needed - self.achieved)

    @property
    def budget(self) -> float:
        return sum(x.budget for x in self.lines)


def needed_contribution(target_profit: float, fixed_costs: float, fixed_revenue: float) -> float:
    return target_profit + fixed_costs - fixed_revenue


def fixed_parts(projection: QuarterProjection) -> tuple[float, float]:
    """(fixed costs, fixed revenue) of a projection."""
    costs = sum(c.p_cost for c in projection.non_marketing)
    revenue = sum(r.p_revenue for r in projection.revenue if r.source == FOLLOW_UP or r.block != "main")
    return costs, revenue


def plan_a(needed: float, sources: list[SourceEconomics]) -> Plan:
    plan, remaining = Plan("A: most efficient first", needed), needed
    usable = sorted((s for s in sources if (s.contribution or 0) > 0), key=lambda s: s.cost_per_deal)
    for s in usable:
        if remaining <= EPS:
            break
        deals = min(math.ceil(remaining / s.contribution - EPS), math.floor(s.max_deals + EPS))
        if deals <= 0:
            continue
        plan.lines.append(PlanLine(s.source, deals, deals * s.cost_per_deal, deals * s.contribution))
        remaining -= deals * s.contribution
    return plan


def plan_b(needed: float, sources: list[SourceEconomics]) -> Plan:
    plan = Plan("B: keep the current mix", needed)
    usable = [s for s in sources if s.contribution is not None and s.projected_deals > 0]
    base = sum(s.projected_deals * s.contribution for s in usable)
    if base <= 0:
        return plan
    plan.k = max(needed, 0.0) / base
    for s in usable:
        deals = plan.k * s.projected_deals
        plan.lines.append(PlanLine(s.source, deals, deals * s.cost_per_deal, deals * s.contribution,
                                   over_cap=deals > s.max_deals + EPS))
    return plan


def source_economics(ds: Dataset, projection: QuarterProjection, months: list[Month],
                     settings: dict) -> list[SourceEconomics]:
    hist = by_source(ds, months)
    r = in_months(ds.revenues, months)
    main = r[r["exit"].map(block_of) == "main"].groupby("source")["revenue"].agg(["sum", "size"])
    done, cap = cost_complete_months(ds), settings.get("scale_cap", 1.5)
    out = []
    for line in projection.marketing:
        src = line.source
        cpd = hist.loc[src, "cost_per_deal"] if src in hist.index else None
        avg = ratio(main.loc[src, "sum"], main.loc[src, "size"]) if src in main.index else None
        p_deals = sum(x.p_deals for x in projection.revenue if x.source == src and x.block == "main")
        out.append(SourceEconomics(src, None if cpd is None or math.isnan(cpd) else float(cpd), avg, p_deals,
                                   best_quarter_spend(ds.costs, src, done), cap))
    return out


def plans(ds: Dataset, projection: QuarterProjection, months: list[Month], settings: dict,
          target_profit: float) -> tuple[Plan, Plan]:
    fixed_costs, fixed_revenue = fixed_parts(projection)
    needed = needed_contribution(target_profit, fixed_costs, fixed_revenue)
    econ = source_economics(ds, projection, months, settings)
    return plan_a(needed, econ), plan_b(needed, econ)
