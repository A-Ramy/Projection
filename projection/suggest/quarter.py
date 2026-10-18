"""Suggestions for one quarter's projection, and accepting them onto its lines.

The history window only uses cost-complete months before the quarter starts, so a quarter never learns from
itself. Accepting copies the value and the inputs onto the line (origin "accepted_suggestion"); typing over an
accepted value makes it an "override". Nothing is ever overwritten silently: when the data moves, the line keeps
its value and is flagged as drifted.
"""

from __future__ import annotations

from dataclasses import dataclass

from projection.data.load import Dataset
from projection.metrics.core import cost_complete_months
from projection.model import CostLine, QuarterProjection, RevenueLine
from projection.periods import Month, Period
from projection.suggest.lookback import label, lookback_months
from projection.suggest.marketing import BudgetSuggestion, suggest_marketing
from projection.suggest.revenue import RevenueSuggestion, suggest_revenue

DRIFT_TOLERANCE = 0.5  # dollars / deals


@dataclass
class QuarterSuggestions:
    months: list[Month]
    budgets: dict[str, BudgetSuggestion]
    revenue: dict[tuple[str, str, str], RevenueSuggestion]

    @property
    def window(self) -> str:
        return label(self.months)


def history_months(ds: Dataset, period: Period, p: QuarterProjection) -> list[Month]:
    before = [m for m in cost_complete_months(ds) if m.last_day < period.start]
    custom = None
    if p.lookback == "custom" and p.lookback_from and p.lookback_to:
        custom = (Month.from_key(p.lookback_from), Month.from_key(p.lookback_to))
    elif p.lookback == "custom":
        return []
    return lookback_months(p.lookback, before, custom)


def quarter_suggestions(ds: Dataset, p: QuarterProjection, period: Period, settings: dict) -> QuarterSuggestions:
    months = history_months(ds, period, p)
    return QuarterSuggestions(
        months=months,
        budgets={s.source: s for s in suggest_marketing(ds, p, months, settings)},
        revenue={(s.block, s.source, s.exit): s for s in suggest_revenue(ds, p, months)},
    )


def accept_budget(line: CostLine, s: BudgetSuggestion) -> bool:
    if s.budget is None:
        return False
    line.p_cost, line.origin = round(s.budget, 2), "accepted_suggestion"
    line.inputs = {"window": s.window, "cost": s.cost, "leads": s.leads, "net_leads": s.net_leads,
                   "deals": s.deals, "target_deals": s.target_deals, "budget": s.budget}
    return True


def accept_revenue(line: RevenueLine, s: RevenueSuggestion) -> bool:
    if s.p_deals is None or s.p_avg is None:
        return False
    line.p_deals, line.p_avg, line.origin = round(s.p_deals, 2), round(s.p_avg, 2), "accepted_suggestion"
    line.inputs = {"quarters": s.quarters, "deals": s.deals, "revenue": s.revenue, "sources": list(s.sources)}
    return True


def mark_typed(line: CostLine | RevenueLine) -> None:
    """A value typed by hand: an override if it replaces an accepted suggestion, else manual."""
    if line.origin != "manual":
        line.origin = "override"


def budget_drift(line: CostLine, s: BudgetSuggestion | None) -> float | None:
    """The current suggestion when it differs from an accepted value (never applied automatically)."""
    if line.origin != "accepted_suggestion" or s is None or s.budget is None:
        return None
    return s.budget if abs(s.budget - line.p_cost) > DRIFT_TOLERANCE else None
