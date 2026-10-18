"""Warnings on a suggestion: insufficient data, low confidence, and the scale flag."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from projection.periods import GRAINS, Month


@dataclass
class Flags:
    insufficient: bool = False  # 0 leads or 0 deals in the window: no suggestion
    low_confidence: bool = False  # fewer than low_conf_min_leads leads or low_conf_min_deals deals
    scale: bool = False  # suggested budget > scale_cap × the source's best quarter since start
    notes: list[str] = field(default_factory=list)

    @property
    def any(self) -> bool:
        return self.insufficient or self.low_confidence or self.scale


def best_quarter_spend(costs: pd.DataFrame, source: str, cost_months: list[Month]) -> float:
    """The source's highest quarterly spend over the cost-complete months since start."""
    done = {m.key for m in cost_months}
    c = costs[(costs["source"] == source) & costs["month"].isin(done)]
    if c.empty:
        return 0.0
    q = c["month"].map(lambda k: GRAINS["quarter"](Month.from_key(k))[0])
    return float(c.groupby(q)["cost"].sum().max())


def check(leads: float, deals: float, budget: float | None, best_quarter: float, settings: dict) -> Flags:
    f = Flags()
    min_leads, min_deals = settings.get("low_conf_min_leads", 30), settings.get("low_conf_min_deals", 3)
    cap = settings.get("scale_cap", 1.5)
    if leads == 0 or deals == 0:
        f.insufficient = True
        f.notes.append(f"Insufficient data: {leads:g} leads and {deals:g} deals in the window.")
        return f
    if leads < min_leads or deals < min_deals:
        f.low_confidence = True
        f.notes.append(f"Low confidence: {leads:g} leads, {deals:g} deals (needs {min_leads}+ leads and "
                       f"{min_deals}+ deals).")
    if budget is not None and budget > cap * best_quarter:
        f.scale = True
        f.notes.append(f"Scale: ${budget:,.2f} is more than {cap:g}× the best quarter since start "
                       f"(${best_quarter:,.2f}).")
    return f
