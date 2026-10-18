"""Lead lifecycle: stage counts, stage-to-stage conversions (period and cohort), money per stage.

Stage events:
    Lead      -> All Leads rows, dated by Date Created
    Net Lead  -> Lead rows with Quality = Qualified, dated by Date (the Quality-change date)
    others    -> KPI rows with KPI = stage, dated by Date (names matched case-insensitively at load)
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

import pandas as pd

from projection.data.load import Dataset
from projection.data.schema import LEAD_KPI
from projection.funnel_config import ALL_CONVERSIONS, LEAKAGE, MAIN_PATH, NET_LEAD
from projection.metrics.core import cost_complete_months, in_months, keys, marketing_names, net_lead_rows, ratio
from projection.periods import Month, Period

STAGES = MAIN_PATH + LEAKAGE
EVENT_COLS = ["stage", "date", "month", "lead_key", "source", "acq", "fus"]


@dataclass(frozen=True)
class Filters:
    sources: tuple[str, ...] | None = None  # None = all sources (company-wide)
    rep_col: str | None = None  # "acq" | "fus"
    rep: str | None = None

    @property
    def by_rep(self) -> bool:
        return bool(self.rep_col and self.rep is not None)

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        if self.sources is not None:
            df = df[df["source"].isin(self.sources)]
        if self.by_rep:
            df = df[df[self.rep_col] == self.rep]
        return df


ALL = Filters()  # company-wide, no filters


def stage_events(ds: Dataset, filters: Filters = ALL) -> pd.DataFrame:
    leads = ds.leads.assign(stage=LEAD_KPI, date=ds.leads["created"])
    net = net_lead_rows(ds).assign(stage=NET_LEAD)
    other = ds.kpis[ds.kpis["kpi"].isin([s for s in STAGES if s not in (LEAD_KPI, NET_LEAD)])]
    other = other.assign(stage=other["kpi"])
    events = pd.concat([f[EVENT_COLS] for f in (leads, net, other)], ignore_index=True)
    return filters.apply(events)


def stage_counts(ds: Dataset, months: Iterable[Month], filters: Filters = ALL) -> pd.Series:
    ev = in_months(stage_events(ds, filters), months)
    return ev["stage"].value_counts().reindex(STAGES, fill_value=0)


def conversions(counts: pd.Series, pairs: Iterable[tuple[str, str]] = ALL_CONVERSIONS) -> pd.DataFrame:
    """Period conversion A→B = Count(B, P) / Count(A, P)."""
    rows = [{"from": a, "to": b, "from_count": int(counts.get(a, 0)), "to_count": int(counts.get(b, 0)),
             "rate": ratio(counts.get(b, 0), counts.get(a, 0))} for a, b in pairs]
    return pd.DataFrame(rows)


def is_immature(month: Month, today: date, immature_months: int) -> bool:
    return month.add(immature_months) > Month.of(today)


def cohort_conversions(ds: Dataset, months: Iterable[Month], filters: Filters = ALL,
                       pairs: Iterable[tuple[str, str]] = ALL_CONVERSIONS, immature_months: int = 2) -> pd.DataFrame:
    """Of the leads (lead_key) that hit A in month m, the share that hit B on or after their first A that month.

    Rows without a lead_key can't be followed and are left out (counted in `unlinked`).
    """
    ev = stage_events(ds, filters)
    unlinked = ev["lead_key"] == ""
    ev = ev[~unlinked]
    present = set(ev["stage"])
    rows = []
    for m in months:
        in_m = ev[ev["month"] == m.key]
        for a, b in pairs:
            starts = in_m[in_m["stage"] == a].groupby("lead_key")["date"].min()
            hit = 0
            if len(starts) and b in present:
                b_dates = ev[(ev["stage"] == b) & ev["lead_key"].isin(starts.index)]
                last_b = b_dates.groupby("lead_key")["date"].max()
                hit = int((last_b.reindex(starts.index) >= starts).sum())
            rows.append({"month": m.key, "from": a, "to": b, "cohort": len(starts), "converted": hit,
                         "rate": ratio(hit, len(starts)), "immature": is_immature(m, ds.today, immature_months)})
    out = pd.DataFrame(rows)
    out.attrs["unlinked"] = int(unlinked.sum())
    return out


def stage_table(ds: Dataset, period: Period | list[Month], settings: dict,
                filters: Filters = ALL) -> pd.DataFrame:
    """Count, conversion from the previous main-path stage and from Lead, and money per stage.

    Cost and profit per stage use the cost-complete months only (counts and revenue from the same months);
    revenue per stage uses all months. Cost is hidden under a rep filter (costs aren't attributable to reps).
    """
    months = list(period.months) if isinstance(period, Period) else list(period)
    done = set(cost_complete_months(ds))
    cmonths = [m for m in months if m in done]
    counts = stage_counts(ds, months, filters)
    ccounts = stage_counts(ds, cmonths, filters)
    rev = filters.apply(in_months(ds.revenues, months))["revenue"].sum()
    crev = filters.apply(in_months(ds.revenues, cmonths))["revenue"].sum()

    costs = in_months(ds.costs, cmonths)
    mkt = marketing_names(ds, settings)
    srcs = set(filters.sources) if filters.sources is not None else mkt
    mkt_cost = costs.loc[costs["source"].isin(srcs & mkt), "cost"].sum()
    all_cost = costs["cost"].sum()
    company = filters.sources is None and not filters.by_rep

    rows, prev = [], None
    for s in STAGES:
        n, cn = int(counts[s]), int(ccounts[s])
        row = {"stage": s, "path": "main" if s in MAIN_PATH else "leakage", "count": n,
               "from_previous": ratio(n, counts[prev]) if prev and s in MAIN_PATH else None,
               "from_lead": ratio(n, counts[LEAD_KPI]),
               "revenue_per": ratio(rev, n),
               "cost_per": None if filters.by_rep else ratio(mkt_cost, cn),
               "profit_per": None if filters.by_rep else ratio(crev - mkt_cost, cn),
               "all_in_cost_per": ratio(all_cost, cn) if company else None,
               "all_in_profit_per": ratio(crev - all_cost, cn) if company else None}
        rows.append(row)
        if s in MAIN_PATH:
            prev = s
    out = pd.DataFrame(rows)
    out.attrs["cost_months"] = keys(cmonths)
    return out


@dataclass(frozen=True)
class ClosedDealCheck:
    kpi_closed: int
    revenue_deals: int

    @property
    def gap(self) -> int:
        return self.revenue_deals - self.kpi_closed

    @property
    def mismatch(self) -> bool:
        return self.gap != 0


def closed_deal_check(ds: Dataset, months: Iterable[Month], filters: Filters = ALL) -> ClosedDealCheck:
    """The KPI Closed Deal count next to the REVENUES deal count (deals always come from REVENUES)."""
    months = list(months)
    kpi = int(stage_counts(ds, months, filters)["Closed Deal"])
    return ClosedDealCheck(kpi, len(filters.apply(in_months(ds.revenues, months))))
