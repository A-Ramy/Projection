"""A quarter's history window (its backbone): only cost-complete months before the quarter starts, so a quarter
never learns from itself."""

from __future__ import annotations

from projection.data.load import Dataset
from projection.metrics.core import cost_complete_months
from projection.model import QuarterProjection
from projection.periods import Month, Period
from projection.suggest.lookback import lookback_months


def history_months(ds: Dataset, period: Period, p: QuarterProjection) -> list[Month]:
    before = [m for m in cost_complete_months(ds) if m.last_day < period.start]
    custom = None
    if p.lookback == "custom" and p.lookback_from and p.lookback_to:
        custom = (Month.from_key(p.lookback_from), Month.from_key(p.lookback_to))
    elif p.lookback == "custom":
        return []
    return lookback_months(p.lookback, before, custom)
