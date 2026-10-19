import streamlit as st

from projection.data import report
from ui import html as h
from ui.layout import fit, issue_list
from ui.state import get_dataset, get_settings

st.title("Data Quality")
h.status("Checks run on every refresh. Nothing is dropped silently: anything skipped or adjusted is listed here.")

ds = get_dataset()
if ds is None:
    st.stop()
settings = get_settings()

sev = {s: sum(1 for i in ds.issues if i.severity == s) for s in ("error", "warning", "info")}
h.tiles([
    ("COSTS Lines", f"{ds.stats['COSTS'].kept:,}", f"Since {ds.start:%b %-d, %Y}"),
    ("REVENUES Deals", f"{ds.stats['REVENUES'].kept:,}", "Every row is a deal"),
    ("KPI Events", f"{ds.stats['KPIs'].kept:,}", f"{len(ds.leads):,} leads by date created"),
    ("Blank KPI Dates", f"{ds.blank_kpi_dates.count:,}",
     f"Not triggered yet; {ds.blank_kpi_dates.leads_counted:,} Pending leads still count in All Leads"),
    ("To Check", f"{sev['error'] + sev['warning']:,}", f"{sev['error']} errors · {sev['warning']} warnings · "
     f"{sev['info']} notes"),
])
h.status(f"Today: {ds.today:%b %-d, %Y} ({ds.timezone}).")

h.heading("Issues")
issue_list(ds.issues)

money = st.column_config.NumberColumn(format="dollar")
h.heading("What's In The Sheet")
t = st.tabs(["Months", "COSTS Names", "Sources", "KPI Values", "Reps"])
with t[0]:
    df = report.months_overview(ds)
    st.dataframe(df, column_config={"cost_total": money, "revenue": money}, height=fit(len(df)))
with t[1]:
    df = report.costs_names(ds, settings)
    st.dataframe(df, column_config={"total": money}, height=fit(len(df)))
with t[2]:
    st.caption("in_tabs: C = COSTS, R = REVENUES, K = KPIs Lead rows. Names are joined on exact text.")
    df = report.sources_overview(ds, settings)
    st.dataframe(df, column_config={"cost": money, "revenue": money}, height=fit(len(df)))
with t[3]:
    vc = report.value_counts(ds)
    cols = st.columns(len(vc))
    for col, (name, df) in zip(cols, vc.items(), strict=False):
        col.markdown(f"**{name}**")
        col.dataframe(df, column_config={"revenue": money}, height=fit(len(df)))
    m, n = report.address_match_rate(ds)
    st.caption(f"Address match for the cohort view: {m:,} of {n:,} REVENUES rows match a KPI address.")
with t[4]:
    df = report.reps(ds)
    st.dataframe(df, hide_index=True, height=fit(len(df)))
