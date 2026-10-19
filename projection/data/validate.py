"""Data checks. Problems are surfaced as Issues, never skipped silently."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

import pandas as pd

from projection.data.keys import name_key
from projection.data.schema import (
    DISQUALIFIED,
    KNOWN_EXITS,
    LEAD_KPI,
    QUALIFIED,
    TAB_COSTS,
    TAB_KPIS,
    TAB_REVENUES,
    Issue,
)
from projection.funnel_config import KPI_STAGES
from projection.periods import Month, cost_complete_through

if TYPE_CHECKING:
    from projection.data.load import Dataset

MAX_EXAMPLES = 12


def _money(x: float) -> str:
    return f"-${abs(x):,.0f}" if x < 0 else f"${x:,.0f}"


def _d(ts) -> str:
    return f"{ts.month}/{ts.day}/{ts.year}"


def validate(ds: Dataset, settings: dict) -> list[Issue]:
    out: list[Issue] = []
    start = ds.start.isoformat()
    costs, revs, kpis = ds.costs, ds.revenues, ds.kpis

    # --- row accounting
    for tab, st in ds.stats.items():
        if st.blank_rows:
            out.append(Issue("info", tab, "blank_rows", f"{tab}: {st.blank_rows} blank separator rows skipped",
                             count=st.blank_rows))
        if st.before_start:
            out.append(Issue("info", tab, "before_start",
                             f"{tab}: {st.before_start:,} rows dated before {start} ignored",
                             detail="Only data from the start date onward is used anywhere in the tool.",
                             count=st.before_start))

    # --- COSTS
    blank_cost = costs[costs["cost_blank"]]
    if len(blank_cost):
        out.append(Issue("warning", TAB_COSTS, "blank_cost", "COSTS: blank cost cells counted as $0",
                         count=len(blank_cost),
                         examples=[f"{Month.from_key(r.month).label} · {r.source} (row {r.sheet_row})"
                                   for r in blank_cost.itertuples()][:MAX_EXAMPLES]))
    if len(costs):
        off = costs[costs["date"].dt.day != costs["date"].dt.days_in_month]
        if len(off):
            dates = sorted({(r.date.normalize(), r.month) for r in off.itertuples()})
            out.append(Issue("info", TAB_COSTS, "not_month_end",
                             "COSTS: dates that aren't the last day of the month (bucketed by month)",
                             count=len(off),
                             examples=[f"{_d(d)} → {Month.from_key(m).label}" for d, m in dates][:MAX_EXAMPLES]))
        dup = costs.groupby(["month", "source"]).size()
        dup = dup[dup > 1]
        if len(dup):
            out.append(Issue("warning", TAB_COSTS, "duplicate_cost_lines",
                             "COSTS: the same Source appears more than once in a month (amounts are added)",
                             count=len(dup),
                             examples=[f"{Month.from_key(m).label} · {s} ×{n}" for (m, s), n in dup.items()]
                             [:MAX_EXAMPLES]))
        last, missing = cost_complete_through({Month.from_key(m) for m in costs["month"]}, ds.today, ds.start)
        if missing:
            out.append(Issue("warning", TAB_COSTS, "missing_cost_months",
                             "COSTS: completed months with no cost rows yet",
                             detail="Cost comparisons stop at the last month with costs posted.",
                             count=len(missing), examples=[m.label for m in missing]))

    # --- names: stray spaces and near-duplicate spellings, within and across tabs
    names: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    spaced: list[str] = []
    for tab, df in ((TAB_COSTS, costs), (TAB_REVENUES, revs), (TAB_KPIS, kpis)):
        for s in df["source"].dropna().unique():
            if not s:
                continue
            names[name_key(s)][s].add(tab)
            if s != s.strip() or "  " in s:
                spaced.append(f"{tab}: {s!r}")
    if spaced:
        out.append(Issue("warning", "ALL", "name_spaces", "Source names with extra spaces",
                         detail="Names are joined on exact text, so these won't match their clean spelling.",
                         count=len(spaced), examples=spaced[:MAX_EXAMPLES]))
    near = [v for v in names.values() if len(v) > 1]
    if near:
        out.append(Issue("warning", "ALL", "near_duplicates", "Near-duplicate source spellings",
                         detail="Same name apart from case or spacing. Not merged automatically.",
                         count=len(near),
                         examples=[" vs ".join(f"{raw!r} ({', '.join(sorted(t))})" for raw, t in v.items())
                                   for v in near][:MAX_EXAMPLES]))

    # --- REVENUES
    def rev_examples(df: pd.DataFrame) -> list[str]:
        return [f"{_d(r.date)} · {r.address or '(no address)'} · {r.exit or '?'} · {r.source or '?'} · "
                f"{_money(r.revenue)} (row {r.sheet_row})" for r in df.itertuples()][:MAX_EXAMPLES]

    checks = [
        ("info", "zero_revenue", "REVENUES: $0 revenue rows (counted as deals)",
         revs[(revs["revenue"] == 0) & ~revs["revenue_blank"]]),
        ("info", "negative_revenue", "REVENUES: negative revenue rows (losses, counted as deals)",
         revs[revs["revenue"] < 0]),
        ("warning", "blank_revenue", "REVENUES: blank Revenue cells counted as $0", revs[revs["revenue_blank"]]),
        ("warning", "blank_source", "REVENUES: rows with no Source", revs[revs["source"].str.strip() == ""]),
        ("warning", "blank_exit", "REVENUES: rows with no Exit Strategy", revs[revs["exit"] == ""]),
        ("warning", "unknown_exit", "REVENUES: exit strategies not in the known list",
         revs[(revs["exit"] != "") & ~revs["exit"].isin(KNOWN_EXITS)]),
        ("warning", "future_close", "REVENUES: Date Closed after today",
         revs[revs["date"].dt.date > ds.today] if len(revs) else revs),
    ]
    for sev, code, title, df in checks:
        if len(df):
            out.append(Issue(sev, TAB_REVENUES, code, title, count=len(df), examples=rev_examples(df)))

    dups = revs[revs["addr_key"] != ""].groupby("addr_key")
    dup_examples = []
    for _, g in dups:
        if len(g) > 1:
            parts = "; ".join(f"{_d(r.date)} {r.exit} {_money(r.revenue)} ({r.source})" for r in g.itertuples())
            dup_examples.append(f"{g.iloc[0]['address']}: {parts}")
    if dup_examples:
        out.append(Issue("info", TAB_REVENUES, "duplicate_addresses",
                         "REVENUES: the same address appears more than once",
                         detail="Each row counts as a deal (your rule); revenue is summed. Review for staged payouts.",
                         count=len(dup_examples), examples=dup_examples[:MAX_EXAMPLES]))

    lead_sources = set(kpis.loc[kpis["kpi"] == LEAD_KPI, "source"]) | set(ds.leads["source"])
    no_leads = sorted(s for s in set(revs["source"]) if s.strip() and s not in lead_sources)
    if no_leads:
        out.append(Issue("warning", TAB_REVENUES, "deals_without_leads",
                         "REVENUES: deals from sources with no Lead KPIs since the start date",
                         detail="Leads per deal and CPL can't be computed for these sources.",
                         count=len(no_leads), examples=no_leads))

    # --- KPIs
    b = ds.blank_kpi_dates
    if b.count:
        q = ", ".join(f"{k}: {v:,}" for k, v in b.by_quality.most_common())
        out.append(Issue("info", TAB_KPIS, "blank_kpi_dates",
                         f"KPIs: {b.count:,} rows with a blank Date (not triggered yet, excluded)",
                         detail=f"By Quality: {q}. Created on/after {start}: {b.created_since_start:,}, of which "
                                f"{b.leads_counted:,} Pending leads still count in All Leads by Date Created.",
                         count=b.count))
    counts = kpis["kpi"].value_counts()
    unknown = [(k, n) for k, n in counts.items() if k not in KPI_STAGES]
    if unknown:
        out.append(Issue("info", TAB_KPIS, "unknown_kpi", "KPIs: KPI values that aren't funnel stages",
                         detail="Counted in PTA; added to the funnel only if listed in funnel_config.py.",
                         count=len(unknown), examples=[f"{k or '(blank)'}: {n:,}" for k, n in unknown]))
    absent = [s for s in KPI_STAGES if s not in counts.index]
    if absent and len(kpis):
        out.append(Issue("info", TAB_KPIS, "missing_stages",
                         "KPIs: funnel stages with no rows since the start date",
                         detail="Expected while a stage simply hasn't happened yet (they show 0); otherwise check the "
                                "spelling in GoHighLevel matches the stage list.",
                         count=len(absent), examples=absent))
    leads = kpis[kpis["kpi"] == LEAD_KPI]
    other_q = leads[~leads["quality"].isin([QUALIFIED, DISQUALIFIED])]["quality"].value_counts()
    if len(other_q):
        out.append(Issue("info", TAB_KPIS, "lead_other_quality",
                         "KPIs: dated Lead rows that are Pending (Quality not Qualified or Disqualified)",
                         detail="Counted in All Leads, not in Net Leads.",
                         count=int(other_q.sum()), examples=[f"{k or '(blank)'}: {n:,}" for k, n in other_q.items()]))
    if len(kpis):
        fut = kpis[kpis["date"].dt.date > ds.today]
        if len(fut):
            out.append(Issue("warning", TAB_KPIS, "future_kpi", "KPIs: Date after today", count=len(fut),
                             examples=[f"row {r.sheet_row}: {_d(r.date)} {r.kpi}" for r in fut.itertuples()]
                             [:MAX_EXAMPLES]))

    # --- the owner's active sources (projected on their own) vs what the sheet holds
    active = list(dict.fromkeys(settings.get("active_sources", [])))
    seen = set(costs["source"]) | set(revs["source"]) | set(kpis["source"]) | set(ds.leads["source"])
    missing = [a for a in active if a not in seen]
    if missing:
        out.append(Issue("warning", "ALL", "active_not_found",
                         "Active sources with no rows in the sheet under this exact name",
                         detail="They still get a row on Projections, but no actuals can attach to them. Check the "
                                "spelling, or rename the sheet's entries to match.",
                         count=len(missing), examples=missing))
    non_mkt = set(settings.get("non_marketing", []))
    if active:
        recent = sorted(costs["month"].unique())[-3:]  # the last three months with costs posted
        stray = costs[costs["month"].isin(recent) & ~costs["source"].isin(set(active) | non_mkt)]
        stray = stray.groupby("source")["cost"].sum()
        stray = stray[stray > 0].sort_values(ascending=False)
        if len(stray):
            out.append(Issue("warning", TAB_COSTS, "spend_not_active",
                             "COSTS: recent marketing spend on sources that aren't on the active list",
                             detail="Last three months with costs. Shown as Other marketing (unprojected) and not "
                                    "projected. Add them to the active "
                                    "list in Settings, or rename them to the active source they belong to.",
                             count=len(stray), examples=[f"{s}: {_money(v)}" for s, v in stray.items()]))
    mkt_no_leads = sorted(s for s in set(costs["source"]) if s not in non_mkt and s not in lead_sources)
    if mkt_no_leads:
        out.append(Issue("info", TAB_COSTS, "spend_without_leads",
                         "COSTS: marketing names with no Lead KPIs since the start date",
                         detail="CPL can't be computed for these; check the name matches KPIs Source exactly.",
                         count=len(mkt_no_leads), examples=mkt_no_leads))
    return out
