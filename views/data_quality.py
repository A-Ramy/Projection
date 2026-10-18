import streamlit as st

from projection.data import report
from ui.layout import issue_list
from ui.state import get_dataset, get_settings

st.title("Data Quality")
st.caption("Checks run on every refresh. Nothing is dropped silently: anything skipped or adjusted is listed here.")

ds = get_dataset()
if ds is None:
    st.stop()
settings = get_settings()

sev = {s: sum(1 for i in ds.issues if i.severity == s) for s in ("error", "warning", "info")}
c = st.columns(6)
c[0].metric("COSTS lines", f"{ds.stats['COSTS'].kept:,}")
c[1].metric("REVENUES deals", f"{ds.stats['REVENUES'].kept:,}")
c[2].metric("KPI events", f"{ds.stats['KPIs'].kept:,}")
c[3].metric("Blank KPI dates", f"{ds.blank_kpi_dates.count:,}",
            help="Not triggered yet; excluded from KPI counts. Pending leads still count in All Leads by Date Created.")
c[4].metric("Errors", sev["error"])
c[5].metric("To check", sev["warning"])
st.caption(f"Only data dated {ds.start:%b %-d, %Y} or later is used. Today: {ds.today:%b %-d, %Y} ({ds.timezone}).")

st.subheader("Issues")
issue_list(ds.issues)

money = st.column_config.NumberColumn(format="dollar")
st.subheader("What's in the sheet")
t = st.tabs(["Months", "COSTS names", "Sources", "KPI values", "Reps"])
with t[0]:
    st.dataframe(report.months_overview(ds), column_config={"cost_total": money, "revenue": money})
with t[1]:
    st.dataframe(report.costs_names(ds, settings), column_config={"total": money})
with t[2]:
    st.caption("in_tabs: C = COSTS, R = REVENUES, K = KPIs Lead rows. Names are joined on exact text.")
    st.dataframe(report.sources_overview(ds, settings), column_config={"cost": money, "revenue": money})
with t[3]:
    vc = report.value_counts(ds)
    cols = st.columns(len(vc))
    for col, (name, df) in zip(cols, vc.items(), strict=False):
        col.markdown(f"**{name}**")
        col.dataframe(df, column_config={"revenue": money})
    m, n = report.address_match_rate(ds)
    st.caption(f"Address match for the cohort view: {m:,} of {n:,} REVENUES rows match a KPI address.")
with t[4]:
    st.dataframe(report.reps(ds), hide_index=True)
