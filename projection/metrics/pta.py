"""Production Trend Analysis: per-rep KPI counts, lead quality, deals and conversion.

A rep dimension names the column used in both KPIs and REVENUES. Adding Lead Agent or DISPO later is
one entry in REP_DIMENSIONS.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

import pandas as pd

from projection.data.keys import street_matches
from projection.data.load import Dataset
from projection.data.schema import DISQUALIFIED, LEAD_KPI, QUALIFIED
from projection.metrics.core import in_months, ratio
from projection.metrics.funnel import ALL, Filters, is_immature
from projection.periods import Month


@dataclass(frozen=True)
class RepDim:
    label: str
    kpi_col: str
    rev_col: str


REP_DIMENSIONS = {d.label: d for d in (RepDim("ACQ", "acq", "acq"), RepDim("FUS", "fus", "fus"))}
BLANK_REP = "(blank)"


def rep_table(ds: Dataset, months: Iterable[Month], dim: str, sources: tuple[str, ...] | None = None) -> pd.DataFrame:
    """One row per rep: All Leads, Qualified / Disqualified (by Quality date), qualification rate, KPI counts by
    type, deals, revenue, avg deal size and period lead→deal."""
    d, months = REP_DIMENSIONS[dim], list(months)
    f = Filters(sources=sources)
    leads = f.apply(in_months(ds.leads, months))
    kpis = f.apply(in_months(ds.kpis, months))
    revs = f.apply(in_months(ds.revenues, months))
    dated_leads = kpis[kpis["kpi"] == LEAD_KPI]

    def by(df: pd.DataFrame, col: str) -> pd.Series:
        return df[col].replace("", BLANK_REP)

    parts = [
        leads.groupby(by(leads, d.kpi_col)).size().rename("leads"),
        dated_leads[dated_leads["quality"] == QUALIFIED].groupby(by(dated_leads, d.kpi_col)).size().rename("qualified"),
        dated_leads[dated_leads["quality"] == DISQUALIFIED].groupby(by(dated_leads, d.kpi_col)).size()
        .rename("disqualified"),
        revs.groupby(by(revs, d.rev_col)).size().rename("deals"),
        revs.groupby(by(revs, d.rev_col))["revenue"].sum(),
    ]
    other = kpis[kpis["kpi"] != LEAD_KPI]
    kpi_counts = other.groupby([by(other, d.kpi_col), "kpi"]).size().unstack(fill_value=0)
    out = pd.concat([*parts, kpi_counts], axis=1).fillna(0)
    out.index.name = dim
    out["qual_rate"] = out["qualified"] / out["leads"].where(out["leads"] != 0)
    out["avg_deal"] = out["revenue"] / out["deals"].where(out["deals"] != 0)
    out["lead_to_deal"] = out["deals"] / out["leads"].where(out["leads"] != 0)
    return out.sort_values(["deals", "leads"], ascending=False)


def lead_to_deal_cohort(ds: Dataset, months: Iterable[Month], filters: Filters = ALL,
                        today: date | None = None, immature_months: int = 2) -> pd.DataFrame:
    """Of the addresses with a lead created in month m, the share whose street matches a REVENUES row
    closed on or after the lead date (REVENUES addresses are street-only, so the match is a prefix test)."""
    today = today or ds.today
    leads = filters.apply(ds.leads)
    leads = leads[leads["addr_key"] != ""]
    rev_rows = [(r.addr_key, r.date) for r in ds.revenues.itertuples() if r.addr_key]  # the address is the deal
    rows = []
    for m in months:
        cohort = leads[leads["month"] == m.key].groupby("addr_key")["created"].min()
        hit = sum(1 for addr, created in cohort.items()
                  if any(street_matches(rk, addr) and closed >= created.normalize() for rk, closed in rev_rows))
        rows.append({"month": m.key, "addresses": len(cohort), "closed": hit, "rate": ratio(hit, len(cohort)),
                     "immature": is_immature(m, today, immature_months)})
    return pd.DataFrame(rows)
