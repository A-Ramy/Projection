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
from projection.funnel_config import ALL_CONVERSIONS, LEAKAGE, MAIN_PATH, NET_LEAD, PREVIOUS
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


def cohort_reach(ds: Dataset, months: Iterable[Month], filters: Filters = ALL) -> pd.DataFrame:
    """The lead cohort of the months (leads created then, with a lead_key), and which stages each reached on or
    after its lead date: one row per lead, one boolean column per stage."""
    ev = stage_events(ds, filters)
    ev = ev[ev["lead_key"] != ""]
    leads = ev[(ev["stage"] == LEAD_KPI) & ev["month"].isin(keys(months))]
    first = leads.groupby("lead_key")["date"].min()
    if first.empty:  # no leads in the months (e.g. no completed month yet)
        return pd.DataFrame(False, index=first.index, columns=STAGES)
    later = ev[ev["lead_key"].isin(first.index)]
    later = later[later["date"] >= later["lead_key"].map(first)]
    reach = later.groupby(["lead_key", "stage"]).size().unstack(fill_value=0) > 0
    return reach.reindex(index=first.index, columns=STAGES, fill_value=False)


def cohort_counts(ds: Dataset, months: Iterable[Month], filters: Filters = ALL) -> pd.Series:
    return cohort_reach(ds, months, filters).sum().reindex(STAGES, fill_value=0).astype(int)


def conversion_rates(ds: Dataset, months: Iterable[Month], filters: Filters = ALL, method: str = "period",
                     pairs: Iterable[tuple[str, str]] = ALL_CONVERSIONS) -> pd.DataFrame:
    """Every listed pair: period = Count(B) / Count(A); cohort = of the period's leads that reached A, the share
    that also reached B."""
    months = list(months)
    if method == "period":
        return conversions(stage_counts(ds, months, filters), pairs)
    reach = cohort_reach(ds, months, filters)
    rows = []
    for a, b in pairs:
        n_a = int(reach[a].sum())
        n_ab = int((reach[a] & reach[b]).sum())
        rows.append({"from": a, "to": b, "from_count": n_a, "to_count": n_ab, "rate": ratio(n_ab, n_a)})
    return pd.DataFrame(rows)


CLOSED_DEAL = "Closed Deal"


def stage_table(ds: Dataset, period: Period | list[Month], settings: dict,
                filters: Filters = ALL, method: str = "period") -> pd.DataFrame:
    """Count, conversion from the previous stage(s) and from Lead, and money per stage.

    method "period" counts events dated in the months; "cohort" counts the months' leads that reached each stage.
    Closed Deal money is per REVENUES deal (every row is a deal), not per KPI Closed Deal.
    Revenue, cost and profit per stage use the cost-complete months only (counts from the same months), so
    profit = revenue − cost on every row; with no cost-complete month (or under a rep filter, where costs aren't
    attributable) revenue per stage uses all the months. In cohort mode revenue and profit per stage are not shown:
    the period's revenue isn't the cohort's revenue.
    """
    months = list(period.months) if isinstance(period, Period) else list(period)
    done = set(cost_complete_months(ds))
    cmonths = [m for m in months if m in done]
    count = cohort_counts if method == "cohort" else stage_counts
    counts = count(ds, months, filters)
    ccounts = count(ds, cmonths, filters)
    rev = filters.apply(in_months(ds.revenues, months))["revenue"].sum()
    crev = filters.apply(in_months(ds.revenues, cmonths))["revenue"].sum()

    costs = in_months(ds.costs, cmonths)
    mkt = marketing_names(ds, settings)
    srcs = set(filters.sources) if filters.sources is not None else mkt
    mkt_cost = costs.loc[costs["source"].isin(srcs & mkt), "cost"].sum()
    all_cost = costs["cost"].sum()
    company = filters.sources is None and not filters.by_rep

    with_costs = bool(cmonths) and not filters.by_rep
    deals = len(filters.apply(in_months(ds.revenues, months)))
    cdeals = len(filters.apply(in_months(ds.revenues, cmonths)))
    rows = []
    for s in STAGES:
        n, cn = int(counts[s]), int(ccounts[s])
        if s == CLOSED_DEAL and method == "period":
            n_money, cn_money = deals, cdeals
        else:
            n_money, cn_money = n, cn
        prev = sum(int(counts[p]) for p in PREVIOUS.get(s, []))
        row = {"stage": s, "path": "main" if s in MAIN_PATH else "leakage", "count": n,
               "previous": " + ".join(PREVIOUS.get(s, [])),
               "from_previous": ratio(n, prev) if s in PREVIOUS else None,
               "from_lead": ratio(n, counts[LEAD_KPI]),
               "revenue_per": None if method == "cohort" else (ratio(crev, cn_money) if with_costs
                                                                else ratio(rev, n_money)),
               "cost_per": ratio(mkt_cost, cn_money) if with_costs else None,
               "profit_per": ratio(crev - mkt_cost, cn_money) if with_costs and method != "cohort" else None,
               "all_in_cost_per": ratio(all_cost, cn_money) if company and with_costs else None,
               "all_in_profit_per": (ratio(crev - all_cost, cn_money) if company and with_costs
                                     and method != "cohort" else None)}
        rows.append(row)
    out = pd.DataFrame(rows)
    out.attrs["cost_months"] = keys(cmonths)
    out.attrs["deals"] = deals
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
