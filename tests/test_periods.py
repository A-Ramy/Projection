from datetime import date

from projection.periods import (
    Month,
    completed_months,
    cost_complete_through,
    elapsed_days,
    parse_period_key,
    period_of,
    periods_covering,
    quarter,
)


def test_month_arithmetic_and_labels():
    assert Month(2026, 12).add(1) == Month(2027, 1)
    assert Month(2026, 1).add(-1) == Month(2025, 12)
    assert Month.from_key("2026-06").label == "Jun 2026"
    assert Month(2026, 2).days == 28


def test_rollups_month_quarter_half_year():
    m = Month(2026, 8)
    assert period_of(m, "month").month_keys == ["2026-08"]
    assert period_of(m, "quarter").label == "Q3 2026"
    assert period_of(m, "quarter").month_keys == ["2026-07", "2026-08", "2026-09"]
    assert period_of(m, "half").key == "2026-H2" and len(period_of(m, "half").months) == 6
    assert len(period_of(m, "year").months) == 12
    assert [p.key for p in periods_covering([Month(2026, 1), Month(2026, 3), Month(2026, 4)], "quarter")] == [
        "2026-Q1", "2026-Q2"]


def test_parse_period_keys():
    assert parse_period_key("2026-Q4").month_keys == ["2026-10", "2026-11", "2026-12"]
    assert parse_period_key("2026-10").label == "Oct 2026"
    assert parse_period_key("2026-H1").months[-1] == Month(2026, 6)


def test_completed_months_respect_start_date():
    assert completed_months(date(2026, 10, 14), date(2026, 1, 1)) == [Month(2026, m) for m in range(1, 10)]
    assert completed_months(date(2026, 1, 20), date(2026, 1, 1)) == []


def test_cost_complete_through_stops_at_first_gap():
    have = {Month(2026, m) for m in range(1, 10)}
    assert cost_complete_through(have, date(2026, 10, 14), date(2026, 1, 1)) == (Month(2026, 9), [])
    gap = have - {Month(2026, 5)}
    last, missing = cost_complete_through(gap, date(2026, 10, 14), date(2026, 1, 1))
    assert last == Month(2026, 4) and missing == [Month(2026, 5)]


def test_quarter_elapsed_days():
    q4 = quarter(2026, 4)
    assert q4.days == 92
    assert elapsed_days(q4, date(2026, 10, 17)) == 17
    assert elapsed_days(q4, date(2026, 9, 30)) == 0
    assert elapsed_days(q4, date(2027, 1, 5)) == 92
