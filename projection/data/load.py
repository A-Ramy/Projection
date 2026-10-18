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
from projection.data.parse import rows_to_records
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
from projection.periods import Month
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

    @property
    def cost_months(self) -> set[Month]:
        return {Month.from_key(m) for m in self.costs["month"].unique()}


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
    ds.issues = sorted(issues + validate(ds, settings), key=lambda i: (i.rank, i.tab, i.code))
    return ds


def load_dataset(secrets: Secrets, settings: dict, today: date | None = None) -> Dataset:
    return build_dataset(fetch_raw(secrets), settings, today=today)
