"""Fetch -> parse -> clean (start-date filter first) -> validate, returning one Dataset."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd

from projection.config import Secrets, parse_start_date
from projection.data.clean import (
    BlankKpiDates,
    TabStats,
    clean_costs,
    clean_kpis,
    clean_revenues,
    links_by_row,
)
from projection.data.keys import HASHED, lead_key
from projection.data.parse import is_blank, rows_to_records, to_text
from projection.data.schema import (
    COSTS_COLUMNS,
    KPIS_COLUMNS,
    REVENUES_COLUMNS,
    TAB_COSTS,
    TAB_KPIS,
    TAB_REVENUES,
    Issue,
)
from projection.data.validate import validate
from projection.periods import Month, months_ago
from projection.sheets import RawSheet, fetch_raw


@dataclass
class Dataset:
    costs: pd.DataFrame
    revenues: pd.DataFrame
    kpis: pd.DataFrame
    leads: pd.DataFrame  # one row per KPI = Lead row, by Date Created (All Leads)
    start: date
    today: date
    timezone: str
    fetched_at: datetime
    stats: dict[str, TabStats] = field(default_factory=dict)
    blank_kpi_dates: BlankKpiDates = field(default_factory=BlankKpiDates)
    issues: list[Issue] = field(default_factory=list)

    complete_cost_months: set[Month] | None = None  # set at build time (see cost_completeness)
    missing_cost_lines: dict[Month, list[str]] = field(default_factory=dict)

    @property
    def cost_months(self) -> set[Month]:
        """Months whose costs are in: every expected line posted, or old enough (see cost_completeness)."""
        if self.complete_cost_months is not None:
            return self.complete_cost_months
        return {Month.from_key(m) for m in self.costs["month"].unique()}


SETTLED_AFTER_MONTHS = 2  # a month this many months back counts as complete with whatever was posted


def cost_completeness(costs: pd.DataFrame, settings: dict, today: date) -> tuple[set[Month], dict[Month, list[str]]]:
    """A month's costs are complete once every line we expect has a COSTS row for it: the payroll lines and the
    active sources that had spend the month before (a new or ended source doesn't hold a month up). A month
    SETTLED_AFTER_MONTHS or more back counts as complete with whatever was posted. A month with no rows at all is
    never complete. Returns the complete months and, for the others with some rows, the lines still missing."""
    expected_names = set(settings.get("active_sources", [])) | set(settings.get("payroll", []))
    posted = costs.groupby("month")["source"].agg(set).to_dict()
    spent = costs[costs["cost"] > 0].groupby("month")["source"].agg(set).to_dict()
    complete, missing = set(), {}
    for key, have in posted.items():
        m = Month.from_key(key)
        expected = spent.get(m.add(-1).key, set()) & expected_names
        gaps = sorted(expected - have)
        if not gaps or months_ago(m, today) >= SETTLED_AFTER_MONTHS:
            complete.add(m)
        else:
            missing[m] = gaps
    return complete, missing


def build_dataset(raw: RawSheet, settings: dict, today: date | None = None,
                  fetched_at: datetime | None = None) -> Dataset:
    tz = raw.timezone or "America/New_York"
    now = datetime.now(ZoneInfo(tz))
    start = parse_start_date(settings)
    issues: list[Issue] = []

    trs = {
        TAB_COSTS: rows_to_records(TAB_COSTS, raw.values.get(TAB_COSTS, []), COSTS_COLUMNS),
        TAB_REVENUES: rows_to_records(TAB_REVENUES, raw.values.get(TAB_REVENUES, []), REVENUES_COLUMNS),
        TAB_KPIS: rows_to_records(TAB_KPIS, raw.values.get(TAB_KPIS, []), KPIS_COLUMNS),
    }
    for tr in trs.values():
        issues += tr.issues

    costs, cst, iss = clean_costs(trs[TAB_COSTS], start)
    issues += iss
    revs, rst, iss = clean_revenues(trs[TAB_REVENUES], start)
    issues += iss
    links = links_by_row(raw.values.get("KPIS_LINK", []))
    kpis, leads, kst, blank, iss = clean_kpis(trs[TAB_KPIS], links, start)
    issues += iss
    del links  # GHL links are only used to derive lead_key

    ds = Dataset(costs=costs, revenues=revs, kpis=kpis, leads=leads, start=start, today=today or now.date(),
                 timezone=tz, fetched_at=fetched_at or now, stats={TAB_COSTS: cst, TAB_REVENUES: rst, TAB_KPIS: kst},
                 blank_kpi_dates=blank)
    ds.complete_cost_months, ds.missing_cost_lines = cost_completeness(costs, settings, ds.today)
    ds.issues = sorted(issues + validate(ds, settings), key=lambda i: (i.rank, i.tab, i.code))
    return ds


def scrub(raw: RawSheet) -> RawSheet:
    """The raw read with every GHL link already replaced by its one-way lead_key, so a cached copy holds no link."""
    links = raw.values.get("KPIS_LINK", [])
    hashed = [links[0] if links else []] + [[HASHED + lead_key(to_text(r[0]))] if r and not is_blank(r[0]) else []
                                             for r in links[1:]]
    return RawSheet(values={**raw.values, "KPIS_LINK": hashed}, timezone=raw.timezone)


def load_dataset(secrets: Secrets, settings: dict, today: date | None = None) -> Dataset:
    return build_dataset(scrub(fetch_raw(secrets)), settings, today=today)
