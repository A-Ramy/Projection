"""Quarter-to-date pacing and end-of-quarter forecasts.

Revenue and KPIs run to today: expected to date = projected × days elapsed / days in quarter, and the
forecast extrapolates the daily rate. Costs only exist for complete months: expected = projected ×
complete months / 3, and the forecast is the average complete month × 3, or the projection itself
(labelled so) when no month is complete yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from projection.metrics.core import ratio
from projection.periods import Month, Period, elapsed_days


@dataclass(frozen=True)
class Pace:
    projected: float
    actual: float
    expected_to_date: float
    forecast: float
    basis: str  # what "to date" means, shown next to the numbers

    @property
    def vs_expected(self) -> float:
        return self.actual - self.expected_to_date

    @property
    def pace_ratio(self) -> float | None:
        return ratio(self.actual, self.expected_to_date)


def daily_pace(period: Period, today: date, projected: float, actual: float) -> Pace:
    """Revenue, deals or KPI counts to today."""
    days = elapsed_days(period, today)
    expected = projected * days / period.days
    forecast = actual / days * period.days if days else 0.0
    return Pace(projected, actual, expected, forecast, f"{days} of {period.days} days")


def cost_pace(period: Period, complete: list[Month], projected: float, actual: float) -> Pace:
    """Costs through the quarter's last cost-complete month."""
    n, total = len(complete), len(period.months)
    expected = projected * n / total
    if n:
        return Pace(projected, actual, expected, actual / n * total, f"costs through {complete[-1].label}")
    return Pace(projected, actual, expected, projected, "no cost month complete yet; forecast = projected")
