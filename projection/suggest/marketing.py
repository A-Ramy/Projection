"""D1: suggested marketing budget per source, and the reverse (budget -> implied leads and deals).

    budget = target deals × leads per deal × CPL = target deals × cost per deal
The result is identical on an All Leads or Net Leads basis; both chains are shown, plus the implied
leads for the budget. Target deals = Σ the source's P.Deals across all its revenue rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from projection.data.load import Dataset
from projection.metrics.core import PARTS, by_source, cost_complete_months, ratio
from projection.model import QuarterProjection
from projection.periods import Month
from projection.suggest.guardrails import Flags, best_quarter_spend, check
from projection.suggest.lookback import label


@dataclass
class BudgetSuggestion:
    source: str
    target_deals: float
    cost: float  # window inputs
    leads: float
    net_leads: float
    deals: float
    best_quarter: float = 0.0
    window: str = ""
    flags: Flags = field(default_factory=Flags)

    @property
    def cpl(self) -> float | None:
        return ratio(self.cost, self.leads)

    @property
    def net_cpl(self) -> float | None:
        return ratio(self.cost, self.net_leads)

    @property
    def lpd(self) -> float | None:
        return ratio(self.leads, self.deals)

    @property
    def net_lpd(self) -> float | None:
        return ratio(self.net_leads, self.deals)

    @property
    def cost_per_deal(self) -> float | None:
        return ratio(self.cost, self.deals)

    @property
    def budget(self) -> float | None:
        if self.flags.insufficient or self.cost_per_deal is None:
            return None
        return self.target_deals * self.cost_per_deal

    @property
    def implied_leads(self) -> float | None:
        return None if self.budget is None or not self.cpl else self.budget / self.cpl

    @property
    def implied_net_leads(self) -> float | None:
        return None if self.budget is None or not self.net_cpl else self.budget / self.net_cpl

    def explain(self) -> list[str]:
        if self.budget is None:
            return self.flags.notes or ["No suggestion."]
        t, out = self.target_deals, []
        if self.lpd is not None and self.cpl is not None:
            out.append(f"All Leads: {t:g} deals × {self.lpd:,.2f} leads/deal × ${self.cpl:,.2f} CPL "
                       f"= ${self.budget:,.2f} ({self.implied_leads:,.0f} leads)")
        if self.net_lpd is not None and self.net_cpl is not None:
            out.append(f"Net Leads: {t:g} deals × {self.net_lpd:,.2f} net leads/deal × ${self.net_cpl:,.2f} "
                       f"Net CPL = ${self.budget:,.2f} ({self.implied_net_leads:,.0f} net leads)")
        out.append(f"= {t:g} deals × ${self.cost_per_deal:,.2f} cost per deal ({self.window}: "
                   f"${self.cost:,.2f} spend, {self.leads:g} leads, {self.deals:g} deals)")
        return out + self.flags.notes


def suggest_budget(source: str, target_deals: float, cost: float, leads: float, net_leads: float, deals: float,
                   settings: dict, best_quarter: float = 0.0, window: str = "") -> BudgetSuggestion:
    s = BudgetSuggestion(source, target_deals, cost, leads, net_leads, deals, best_quarter, window)
    s.flags = check(leads, deals, None, best_quarter, settings)
    if not s.flags.insufficient:
        s.flags = check(leads, deals, s.budget, best_quarter, settings)
    return s


@dataclass(frozen=True)
class Reverse:
    budget: float
    implied_leads: float | None
    implied_net_leads: float | None
    implied_deals: float | None


def reverse(budget: float, cost: float, leads: float, deals: float, net_leads: float = 0) -> Reverse:
    """An overridden budget: implied leads = budget / CPL; implied deals = implied leads / LPD."""
    cpl, net_cpl, lpd = ratio(cost, leads), ratio(cost, net_leads), ratio(leads, deals)
    implied = budget / cpl if cpl else None
    deals_out = implied / lpd if implied is not None and lpd else None
    return Reverse(budget, implied, budget / net_cpl if net_cpl else None, deals_out)


def suggest_marketing(ds: Dataset, projection: QuarterProjection, months: list[Month],
                      settings: dict) -> list[BudgetSuggestion]:
    """One suggestion per projected marketing source (non-marketing lines get none)."""
    hist = by_source(ds, months)
    done, window = cost_complete_months(ds), label(months)
    out = []
    for line in projection.marketing:
        h = hist.loc[line.source] if line.source in hist.index else {c: 0.0 for c in PARTS}
        out.append(suggest_budget(
            line.source, projection.target_deals(line.source), float(h["cost"]), float(h["leads"]),
            float(h["net_leads"]), float(h["deals"]), settings, best_quarter_spend(ds.costs, line.source, done),
            window))
    return out
