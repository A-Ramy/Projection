"""Backtest: predict a finished quarter with only the months before it, then compare with what happened.

Per marketing source, from the window: predicted deals = deals ÷ quarters, budget = deals × cost per deal (using
the predicted deals, or the quarter's actual deals to test the budget formula on its own), leads = deals × leads
per deal, revenue = deals × avg deal size. Errors are (predicted − actual) ÷ actual; MAPE is their mean absolute.
"""

from __future__ import annotations

from dataclasses import dataclass

from projection.data.load import Dataset
from projection.metrics.core import by_source, marketing_names, ratio
from projection.model import QuarterProjection
from projection.periods import Period
from projection.suggest.lookback import label
from projection.suggest.quarter import history_months

METRICS = ("budget", "leads", "deals", "revenue")


@dataclass
class BacktestRow:
    source: str
    window_cost: float
    window_leads: float
    window_deals: float
    window_revenue: float
    quarters: float
    actual_budget: float
    actual_leads: float
    actual_deals: float
    actual_revenue: float
    actual_deals_basis: bool = False  # budget tested with the quarter's actual deals

    @property
    def predictable(self) -> bool:
        return self.window_deals > 0 and self.window_cost > 0 and self.quarters > 0

    @property
    def note(self) -> str:
        if self.predictable:
            return ""
        return "No spend in the window" if self.window_cost <= 0 else "No closed deals in the window"

    @property
    def pred_deals(self) -> float | None:
        return ratio(self.window_deals, self.quarters) if self.predictable else None

    @property
    def pred_budget(self) -> float | None:
        if not self.predictable:
            return None
        deals = self.actual_deals if self.actual_deals_basis else self.pred_deals
        return deals * self.window_cost / self.window_deals

    @property
    def pred_leads(self) -> float | None:
        return self.pred_deals * self.window_leads / self.window_deals if self.predictable else None

    @property
    def pred_revenue(self) -> float | None:
        return self.pred_deals * self.window_revenue / self.window_deals if self.predictable else None

    def error(self, metric: str) -> float | None:
        p, a = getattr(self, f"pred_{metric}"), getattr(self, f"actual_{metric}")
        return None if p is None or not a else (p - a) / a


@dataclass
class Backtest:
    target: Period
    window: list
    rows: list[BacktestRow]

    @property
    def window_label(self) -> str:
        return label(self.window)

    def mape(self, metric: str) -> float | None:
        errs = [abs(e) for r in self.rows if (e := r.error(metric)) is not None]
        return sum(errs) / len(errs) if errs else None


def backtest(ds: Dataset, target: Period, settings: dict, lookback: str = "last_2_quarters",
             actual_deals_basis: bool = False) -> Backtest:
    window = history_months(ds, target, QuarterProjection(quarter_id=target.key, lookback=lookback))
    hist, act = by_source(ds, window), by_source(ds, target.months)
    mkt = marketing_names(ds, settings)
    sources = sorted(s for s in mkt if (s in hist.index and hist.loc[s, "cost"] > 0)
                     or (s in act.index and act.loc[s, "cost"] > 0))

    def get(df, s, c):
        return float(df.loc[s, c]) if s in df.index else 0.0

    rows = [BacktestRow(s, get(hist, s, "cost"), get(hist, s, "leads"), get(hist, s, "deals"),
                        get(hist, s, "revenue"), len(window) / 3, get(act, s, "cost"), get(act, s, "leads"),
                        get(act, s, "deals"), get(act, s, "revenue"), actual_deals_basis) for s in sources]
    return Backtest(target, window, rows)
