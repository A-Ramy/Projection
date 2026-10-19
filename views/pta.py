"""PTA (Production Trend Analysis): per-rep leaderboard, trend per rep, and KPI counts by type."""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from projection.funnel_config import KPI_STAGES
from projection.metrics.core import keys
from projection.metrics.pta import LEADERBOARD, leaderboard, rep_table
from projection.periods import Month, month_range, periods_in_range
from ui import html as h
from ui.brand import plotly_layout, series_colors
from ui.state import get_dataset

FMT = {"Leads": h.num, "Net Leads": h.num, "Qual. Rate": h.pct, "Appts Set": h.num, "Appts Held": h.num,
       "Offers": h.num, "Contracts Signed": h.num, "Deals": h.num, "Revenue": h.money, "Avg Deal": h.money,
       "Lead→Deal": h.pct}

ds = get_dataset()
if ds is None:
    st.stop()

st.title("PTA")
months = month_range(Month.of(ds.start), Month.of(ds.today))
sources = sorted((set(ds.leads["source"]) | set(ds.revenues["source"])) - {""})

c = st.columns([2, 2.6, 2, 2.4], vertical_alignment="bottom")
dim = c[0].segmented_control("View", ["ACQ", "FUS"], default="ACQ", key="pta_dim", format_func=lambda d: f"{d} View")
dim = dim or "ACQ"
src = c[1].selectbox("Source", ["All Sources"] + sources, key="pta_src")
grain = c[2].segmented_control("Group By", ["month", "quarter"], default="month", key="pta_grain",
                               format_func=lambda g: "Monthly" if g == "month" else "Quarterly") or "month"
conv = c[3].segmented_control("Lead → Deal", ["period", "cohort"], default="period", key="pta_conv",
                              format_func=lambda m: "Period Ratio" if m == "period" else "Cohort") or "period"
r1, r2 = st.columns(2)
last_full = months[-2] if len(months) > 1 else months[-1]  # a month in progress would skew the arrows
first, last = r1.select_slider("Period Range", options=months, value=(months[0], last_full),
                               format_func=lambda m: m.label, key="pta_range")
sel_sources = None if src == "All Sources" else (src,)

periods = periods_in_range(first, last, grain)
cur, prev = periods[-1], (periods[-2] if len(periods) > 1 else None)
board = leaderboard(ds, cur.months, dim, sel_sources, conv)
prev_board = leaderboard(ds, prev.months, dim, sel_sources, conv) if prev else None
all_reps = list(leaderboard(ds, [m for p in periods for m in p.months], dim, sel_sources)
                .sort_values(["Deals", "Leads"], ascending=False).index)
reps = r2.pills("Reps", all_reps, selection_mode="multi", default=all_reps[:6], key=f"pta_reps_{dim}")
reps = reps or all_reps[:6]
colors = series_colors(all_reps)  # color follows the rep, not the rank or the selection

if conv == "cohort":
    h.box("Cohort view: of the leads created in a period, the share whose address later closed. Recent periods look "
          "low because those leads haven't had time to close yet.", "warn")
today_note = f" · {Month.of(ds.today).label} is month-to-date" if Month.of(ds.today) in cur.months else ""
h.heading("Leaderboard", None, f"{cur.label}{f' · arrows compare with {prev.label}' if prev else ''}{today_note}")
rows = []
shown = board.loc[[r for r in board.sort_values("Revenue", ascending=False).index if r in reps]]
for i, (rep, row) in enumerate(shown.iterrows(), 1):
    cells = [str(i), h.sw(colors.get(rep, "#888")) + h.esc(rep)]
    for col in LEADERBOARD:
        pv = prev_board.loc[rep, col] if prev_board is not None and rep in prev_board.index else None
        cells.append(FMT[col](row[col]) + h.arrow(row[col], pv))
    rows.append(cells)
h.show(h.table(["#", f"{dim} Rep", *LEADERBOARD], rows, left=(0, 1)) if rows
       else '<p class="status">No activity for these reps in this period.</p>')

with st.container(key="card-trend"):
    t1, t2 = st.columns([3, 1.4], vertical_alignment="bottom")
    t1.html('<div class="sh"><span class="t1">Trend Per Rep</span></div>')
    metric = t2.selectbox("Metric", LEADERBOARD, index=LEADERBOARD.index("Deals"), key="pta_metric")
    labels = [p.label for p in periods]
    data = {p.key: leaderboard(ds, p.months, dim, sel_sources, conv) for p in periods}
    fig = go.Figure()
    for rep in reps:
        ys = [data[p.key].loc[rep, metric] if rep in data[p.key].index else None for p in periods]
        fig.add_trace(go.Scatter(x=labels, y=ys, name=rep, mode="lines+markers", line=dict(width=2, color=colors[rep]),
                                 marker=dict(size=8, line=dict(width=2, color="rgba(255,255,255,.9)"))))
    layout = plotly_layout()
    layout["yaxis"]["tickformat"] = {"Qual. Rate": ".0%", "Lead→Deal": ".0%"}.get(metric, ",.0f")
    top = max((y for t in fig.data for y in t.y if y is not None and y == y), default=0)
    if layout["yaxis"]["tickformat"] == ",.0f" and top < 10:
        layout["yaxis"] |= {"tickformat": ",d", "dtick": 1, "rangemode": "tozero"}  # small counts: whole ticks
    if metric in ("Revenue", "Avg Deal"):
        layout["yaxis"]["tickprefix"] = "$"
    fig.update_layout(**layout, height=320)
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

h.heading("KPI Counts By Type", None, f"{cur.label}, by KPI date (Lead by date created)")
t = rep_table(ds, cur.months, dim, sel_sources)
stage_cols = [s for s in KPI_STAGES if s != "Lead"]
rows = [[h.esc(rep), h.num(t.loc[rep, "leads"]), h.num(t.loc[rep, "qualified"]), h.num(t.loc[rep, "disqualified"])]
        + [h.num(t.loc[rep, s]) if s in t.columns else "0" for s in stage_cols]
        for rep in t.index if rep in reps]
h.show(h.table(["Rep", "Lead", "Qualified", "Disqualified", *stage_cols], rows))
st.caption(f"Months covered: {', '.join(Month.from_key(k).label for k in keys(cur.months))}. Lead counts every "
           "lead by the day it came in (Pending included); Qualified / Disqualified are dated by the Quality change.")
