"""Aggregate-only data report (no names, phones or links): used by scripts/profile.py and the
Data Quality page. Each section is a DataFrame; to_markdown() renders the whole report."""

from __future__ import annotations

import pandas as pd

from projection.data.load import Dataset
from projection.data.schema import LEAD_KPI, QUALIFIED
from projection.periods import Month


def _net_leads(ds: Dataset) -> pd.DataFrame:
    return ds.kpis[(ds.kpis["kpi"] == LEAD_KPI) & (ds.kpis["quality"] == QUALIFIED)]


def months_overview(ds: Dataset) -> pd.DataFrame:
    c = ds.costs.groupby("month").agg(cost_lines=("cost", "size"), cost_total=("cost", "sum"))
    r = ds.revenues.groupby("month").agg(deals=("revenue", "size"), revenue=("revenue", "sum"))
    k = ds.kpis.groupby("month").agg(kpi_events=("kpi", "size"))
    leads = ds.leads.groupby("month").agg(leads=("source", "size"))
    net = _net_leads(ds).groupby("month").agg(net_leads=("source", "size"))
    out = pd.concat([c, r, k, leads, net], axis=1).fillna(0).sort_index()
    out.index = pd.Index([Month.from_key(m).label for m in out.index], name="month")
    return out.astype({c: "int64" for c in ["cost_lines", "deals", "kpi_events", "leads", "net_leads"]})


def costs_names(ds: Dataset, settings: dict) -> pd.DataFrame:
    non = set(settings.get("non_marketing", []))
    g = ds.costs.groupby("source").agg(
        total=("cost", "sum"), months=("month", lambda s: ", ".join(Month.from_key(m).label[:3]
                                                                    for m in sorted(s.unique()))),
        blank_cells=("cost_blank", "sum"))
    g.insert(0, "class", ["non-marketing" if s in non else "marketing" for s in g.index])
    return g.sort_values(["class", "total"], ascending=[True, False])


def sources_overview(ds: Dataset, settings: dict) -> pd.DataFrame:
    non = set(settings.get("non_marketing", []))
    cost = ds.costs[~ds.costs["source"].isin(non)].groupby("source")["cost"].sum().rename("cost")
    deals = ds.revenues.groupby("source").agg(deals=("revenue", "size"), revenue=("revenue", "sum"))
    leads = ds.leads.groupby("source").agg(leads=("month", "size"))
    net = _net_leads(ds).groupby("source").agg(net_leads=("month", "size"))
    out = pd.concat([cost, deals, leads, net], axis=1).fillna(0)
    out["in_tabs"] = [
        "/".join(t for t, present in (("C", s in cost.index), ("R", s in deals.index),
                                                     ("K", s in leads.index or s in net.index))
                 if present) for s in out.index]
    return out.astype({"deals": "int64", "leads": "int64", "net_leads": "int64"}).sort_values(
        ["cost", "leads"], ascending=False)


def value_counts(ds: Dataset) -> dict[str, pd.DataFrame]:
    k = ds.kpis
    def vc(series, name):
        return series.replace("", "(blank)").value_counts().rename_axis(name).to_frame("rows")
    return {
        "KPI": vc(k["kpi"], "KPI"),
        "Lead Quality": ds.leads["quality"].value_counts().rename_axis("Quality").to_frame("leads"),
        "Stage": vc(k["stage"], "Stage"),
        "Exit Strategy": ds.revenues.groupby(ds.revenues["exit"].replace("", "(blank)")).agg(
            deals=("revenue", "size"), revenue=("revenue", "sum")).sort_values("deals", ascending=False),
    }


def reps(ds: Dataset) -> pd.DataFrame:
    rows = []
    for col, label in (("acq", "ACQ"), ("fus", "FUS"), ("lead_agent", "Lead Agent")):
        for name, n in ds.kpis[col].replace("", "(blank)").value_counts().items():
            rows.append({"role": label, "name": name, "kpi_rows": int(n)})
    rev = {}
    for col, label in (("acq", "ACQ"), ("fus", "FUS"), ("dispo", "DISPO"), ("agent", "AGENT"),
                       ("dispo_lm", "DISPO LM")):
        for name, n in ds.revenues[col].replace("", "(blank)").value_counts().items():
            rev[(label, name)] = int(n)
    df = pd.DataFrame(rows, columns=["role", "name", "kpi_rows"])
    df["deals"] = [rev.pop((r.role, r.name), 0) for r in df.itertuples()]
    extra = pd.DataFrame([{"role": k[0], "name": k[1], "kpi_rows": 0, "deals": v} for k, v in rev.items()])
    return pd.concat([df, extra], ignore_index=True) if len(extra) else df


def address_match_rate(ds: Dataset) -> tuple[int, int]:
    """REVENUES rows whose street matches a KPI address (for the cohort view)."""
    kpi_keys = set(ds.kpis["addr_key"]) - {""}
    prefixes = set()
    for k in kpi_keys:
        toks = k.split()
        prefixes.update(" ".join(toks[:i]) for i in range(2, len(toks) + 1))
    rev = [k for k in ds.revenues["addr_key"] if k]  # a match = whole-token prefix of a KPI street key
    return sum(1 for k in rev if k in prefixes), len(rev)


def _md_table(df: pd.DataFrame, money: tuple[str, ...] = ()) -> str:
    if df.empty:
        return "_none_\n"
    df = df.reset_index()
    cols = list(df.columns)
    def fmt(c, v):
        if c in money and isinstance(v, (int, float)):
            return f"${v:,.2f}"
        if isinstance(v, float):
            return f"{v:,.2f}" if not v.is_integer() else f"{int(v):,}"
        if isinstance(v, int):
            return f"{v:,}"
        return str(v).replace("|", "\\|")
    lines = ["| " + " | ".join(map(str, cols)) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(fmt(c, v) for c, v in zip(cols, row, strict=False)) + " |" for row in df.values]
    return "\n".join(lines) + "\n"


def to_markdown(ds: Dataset, settings: dict) -> str:
    s = ds.stats
    out = [
        "# Data report (aggregates only)",
        f"Fetched {ds.fetched_at:%Y-%m-%d %H:%M} ({ds.timezone}) · start date {ds.start} · today {ds.today}\n",
        "## Rows",
        _md_table(pd.DataFrame(
            {tab: {"rows kept (≥ start)": st.kept, "rows before start": st.before_start,
                   "blank/separator rows": st.blank_rows} for tab, st in s.items()}).T.rename_axis("tab")),
        "## Months covered",
        _md_table(months_overview(ds), money=("cost_total", "revenue")),
        "## COSTS names and proposed split",
        _md_table(costs_names(ds, settings), money=("total",)),
        "## Sources across tabs (C = COSTS, R = REVENUES, K = KPIs Lead rows)",
        "leads = All Leads by Date Created; net_leads = Qualified, by the Quality-change Date.\n",
        _md_table(sources_overview(ds, settings), money=("cost", "revenue")),
    ]
    for name, df in value_counts(ds).items():
        out += [f"## Distinct values: {name}", _md_table(df, money=("revenue",))]
    b = ds.blank_kpi_dates
    out += ["## Blank KPI Dates (excluded from KPI counts; Pending leads still count in All Leads)",
            f"{b.count:,} rows. By Quality: " + ", ".join(f"{k}: {v:,}" for k, v in b.by_quality.most_common())
            + ". By KPI: " + ", ".join(f"{k}: {v:,}" for k, v in b.by_kpi.most_common())
            + f". Created on/after {ds.start}: {b.created_since_start:,}"
            + f" ({b.leads_counted:,} Lead rows counted in All Leads by Date Created).\n"]
    m, n = address_match_rate(ds)
    out += ["## Address match (REVENUES street → KPIs address)",
            f"{m:,} of {n:,} REVENUES rows match a KPI address ({(m / n * 100) if n else 0:.0f}%).\n",
            "## Reps", _md_table(reps(ds)), "## Issues"]
    for i in ds.issues:
        out.append(f"- **[{i.severity}] {i.title}**" + (f" ({i.count:,})" if i.count else "")
                   + (f" — {i.detail}" if i.detail else ""))
        out += [f"    - {e}" for e in i.examples]
    return "\n".join(out) + "\n"
