"""Per-source monthly parts (cost, leads, net leads, deals, revenue) and the ratios built from them.

Parts are summed first, at the monthly grain, then rolled up; ratios are always recomputed from the
summed parts (never averaged across months).
    All Leads  = KPI = Lead rows by Date Created (any Quality, incl. Pending)
    Net Leads  = Lead rows with Quality = Qualified, by Date (the Quality-change date)
    Deals      = REVENUES rows (every row is a deal), across all exits
"""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from projection.data.load import Dataset
from projection.data.schema import LEAD_KPI, QUALIFIED, block_of
from projection.periods import GRAINS, Month, Period, cost_complete_through, month_range

PARTS = ["cost", "leads", "net_leads", "deals", "revenue"]
RATIOS = {  # name -> (numerator, denominator)
    "cpl": ("cost", "leads"),
    "net_cpl": ("cost", "net_leads"),
    "lpd": ("leads", "deals"),
    "net_lpd": ("net_leads", "deals"),
    "cost_per_deal": ("cost", "deals"),
    "avg_deal": ("revenue", "deals"),
    "qual_rate": ("net_leads", "leads"),
    "lead_to_deal": ("deals", "leads"),
}


def ratio(num: float, den: float) -> float | None:
    """num / den, or None when the denominator is 0 (shown as 'insufficient data', never as 0)."""
    return num / den if den else None


def keys(months: Iterable[Month]) -> list[str]:
    return [m.key for m in months]


def in_months(df: pd.DataFrame, months: Iterable[Month]) -> pd.DataFrame:
    return df[df["month"].isin(keys(months))]


def marketing_names(ds: Dataset, settings: dict) -> set[str]:
    non = set(settings.get("non_marketing", []))
    return {s for s in ds.costs["source"].unique() if s not in non}


def net_lead_rows(ds: Dataset) -> pd.DataFrame:
    k = ds.kpis
    return k[(k["kpi"] == LEAD_KPI) & (k["quality"] == QUALIFIED)]


def cost_complete_months(ds: Dataset) -> list[Month]:
    """Completed months ≥ start with costs posted, up to the first gap."""
    last, _ = cost_complete_through(ds.cost_months, ds.today, ds.start)
    return month_range(Month.of(ds.start), last) if last else []


def complete_in(period: Period, ds: Dataset) -> list[Month]:
    done = set(cost_complete_months(ds))
    return [m for m in period.months if m in done]


def source_month(ds: Dataset) -> pd.DataFrame:
    """Long table: one row per (month, source) with the five parts."""
    frames = [
        ds.costs.groupby(["month", "source"])["cost"].sum(),
        ds.leads.groupby(["month", "source"]).size().rename("leads"),
        net_lead_rows(ds).groupby(["month", "source"]).size().rename("net_leads"),
        ds.revenues.groupby(["month", "source"]).size().rename("deals"),
        ds.revenues.groupby(["month", "source"])["revenue"].sum(),
    ]
    out = pd.concat(frames, axis=1).reindex(columns=PARTS).fillna(0.0)
    out.index.names = ["month", "source"]
    return out.reset_index()


def add_ratios(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for name, (num, den) in RATIOS.items():
        df[name] = df[num] / df[den].where(df[den] != 0)
    return df


def by_source(ds: Dataset, months: Iterable[Month], sources: Iterable[str] | None = None) -> pd.DataFrame:
    """Parts summed over the months, per source, with ratios. Cost covers the months given: pass
    cost-complete months when comparing costs."""
    sm = in_months(source_month(ds), months)
    if sources is not None:
        sm = sm[sm["source"].isin(list(sources))]
    return add_ratios(sm.groupby("source")[PARTS].sum())


def rollup(df: pd.DataFrame, grain: str, by: list[str] | None = None) -> pd.DataFrame:
    """Sum a monthly long table (with a 'month' column) into periods of the grain, then add ratios."""
    by = by or []
    period_key = df["month"].map(lambda k: GRAINS[grain](Month.from_key(k))[0])
    parts = [c for c in PARTS if c in df.columns]
    out = df.assign(period=period_key).groupby(["period", *by])[parts].sum()
    return add_ratios(out) if set(PARTS) <= set(parts) else out


def revenue_by(ds: Dataset, months: Iterable[Month], by: tuple[str, ...] = ("source", "exit")) -> pd.DataFrame:
    """Deals, revenue and avg deal size grouped by REVENUES columns (and 'block')."""
    r = in_months(ds.revenues, months).assign(block=lambda d: d["exit"].map(block_of))
    out = r.groupby(list(by)).agg(deals=("revenue", "size"), revenue=("revenue", "sum"))
    out["avg_deal"] = out["revenue"] / out["deals"]
    return out


def pct_base(ds: Dataset, months: Iterable[Month], settings: dict) -> float:
    """Revenue base for P.% / A.%: total revenue minus the excluded exits (default F&F, B&H)."""
    r = in_months(ds.revenues, months)
    return float(r.loc[~r["exit"].isin(settings.get("pct_base_excluded_exits", [])), "revenue"].sum())
