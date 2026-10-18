"""Monthly grain and roll-ups.

Every metric is computed per month first, then summed into a Period. A grain is one entry in
GRAINS (month, quarter, half, year), so new roll-ups need no restructuring.
"""

from __future__ import annotations

import calendar
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date

MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


@dataclass(frozen=True, order=True)
class Month:
    year: int
    month: int

    @classmethod
    def of(cls, d: date) -> Month:
        return cls(d.year, d.month)

    @classmethod
    def from_key(cls, key: str) -> Month:
        y, m = key.split("-")
        return cls(int(y), int(m))

    @property
    def key(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"

    @property
    def label(self) -> str:
        return f"{MONTH_NAMES[self.month - 1]} {self.year}"

    @property
    def quarter(self) -> int:
        return (self.month - 1) // 3 + 1

    @property
    def first_day(self) -> date:
        return date(self.year, self.month, 1)

    @property
    def last_day(self) -> date:
        return date(self.year, self.month, calendar.monthrange(self.year, self.month)[1])

    @property
    def days(self) -> int:
        return calendar.monthrange(self.year, self.month)[1]

    def add(self, n: int) -> Month:
        idx = self.year * 12 + (self.month - 1) + n
        return Month(idx // 12, idx % 12 + 1)

    def __str__(self) -> str:
        return self.key


@dataclass(frozen=True)
class Period:
    grain: str
    key: str
    label: str
    months: tuple[Month, ...]

    @property
    def start(self) -> date:
        return self.months[0].first_day

    @property
    def end(self) -> date:
        return self.months[-1].last_day

    @property
    def days(self) -> int:
        return sum(m.days for m in self.months)

    @property
    def month_keys(self) -> list[str]:
        return [m.key for m in self.months]


def _span(first: Month, n: int) -> tuple[Month, ...]:
    return tuple(first.add(i) for i in range(n))


# grain -> month -> (key, label, months-in-period)
GRAINS: dict[str, Callable[[Month], tuple[str, str, tuple[Month, ...]]]] = {
    "month": lambda m: (m.key, m.label, (m,)),
    "quarter": lambda m: (
        f"{m.year}-Q{m.quarter}",
        f"Q{m.quarter} {m.year}",
        _span(Month(m.year, 3 * m.quarter - 2), 3),
    ),
    "half": lambda m: (
        f"{m.year}-H{1 if m.month <= 6 else 2}",
        f"H{1 if m.month <= 6 else 2} {m.year}",
        _span(Month(m.year, 1 if m.month <= 6 else 7), 6),
    ),
    "year": lambda m: (str(m.year), str(m.year), _span(Month(m.year, 1), 12)),
}


def period_of(month: Month, grain: str) -> Period:
    key, label, months = GRAINS[grain](month)
    return Period(grain, key, label, months)


def quarter(year: int, q: int) -> Period:
    return period_of(Month(year, 3 * q - 2), "quarter")


def parse_period_key(key: str) -> Period:
    """'2026-Q4', '2026-H1', '2026', '2026-10'."""
    if "-Q" in key:
        y, q = key.split("-Q")
        return quarter(int(y), int(q))
    if "-H" in key:
        y, h = key.split("-H")
        return period_of(Month(int(y), 1 if h == "1" else 7), "half")
    if "-" in key:
        return period_of(Month.from_key(key), "month")
    return period_of(Month(int(key), 1), "year")


def month_range(first: Month, last: Month) -> list[Month]:
    out, m = [], first
    while m <= last:
        out.append(m)
        m = m.add(1)
    return out


def periods_covering(months: Iterable[Month], grain: str) -> list[Period]:
    seen: dict[str, Period] = {}
    for m in sorted(set(months)):
        p = period_of(m, grain)
        seen.setdefault(p.key, p)
    return list(seen.values())


def completed_months(today: date, start: date) -> list[Month]:
    """Whole months from the start month up to (not including) today's month."""
    first, current = Month.of(start), Month.of(today)
    return month_range(first, current.add(-1)) if first < current else []


def cost_complete_through(
    months_with_costs: Iterable[Month], today: date, start: date
) -> tuple[Month | None, list[Month]]:
    """Costs are posted as month totals at month end, so a month in progress has none.

    Returns the last completed month such that it and every completed month before it have cost
    rows, plus the completed months still missing costs (to surface, not hide).
    """
    have = set(months_with_costs)
    done = completed_months(today, start)
    last: Month | None = None
    for m in done:
        if m not in have:
            break
        last = m
    missing = [m for m in done if m not in have]
    return last, missing


def elapsed_days(period: Period, today: date) -> int:
    """Days of the period elapsed through today (inclusive), clamped to the period."""
    if today < period.start:
        return 0
    if today >= period.end:
        return period.days
    return (today - period.start).days + 1
