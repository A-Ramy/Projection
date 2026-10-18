"""The history window suggestions learn from: whole, cost-complete months on or after the start date."""

from __future__ import annotations

from projection.periods import Month, month_range

LOOKBACKS = {
    "last_quarter": "Last completed quarter",
    "last_2_quarters": "Last 2 quarters",
    "all": "All since start",
    "custom": "Custom month range",
}
DEFAULT_LOOKBACK = "last_quarter"


def complete_quarters(cost_months: list[Month]) -> list[list[Month]]:
    """Calendar quarters whose three months are all cost-complete, oldest first."""
    have = set(cost_months)
    starts = sorted({Month(m.year, 3 * m.quarter - 2) for m in have})
    return [q for q in ([s, s.add(1), s.add(2)] for s in starts) if all(m in have for m in q)]


def lookback_months(option: str, cost_months: list[Month],
                    custom: tuple[Month, Month] | None = None) -> list[Month]:
    """cost_months = the cost-complete months since start (metrics.core.cost_complete_months)."""
    if option == "custom":
        if not custom:
            raise ValueError("A custom lookback needs a first and last month.")
        have = set(cost_months)
        return [m for m in month_range(*custom) if m in have]
    if option == "all":
        return list(cost_months)
    quarters = complete_quarters(cost_months)
    n = {"last_quarter": 1, "last_2_quarters": 2}.get(option)
    if n is None:
        raise ValueError(f"Unknown lookback {option!r}; choose one of {', '.join(LOOKBACKS)}.")
    return [m for q in quarters[-n:] for m in q]


def label(months: list[Month]) -> str:
    if not months:
        return "no complete months"
    return months[0].label if len(months) == 1 else f"{months[0].label} – {months[-1].label}"
