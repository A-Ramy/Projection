"""Funnel: the lead lifecycle with leaks, cost vs profit per stage, every stage, and the conversion matrix."""

from __future__ import annotations

import streamlit as st

from projection.funnel_config import ADDED, ALL_CONVERSIONS, LEAKAGE, LIVE_TRANSFER, MAIN_PATH, PREVIOUS
from projection.metrics.core import cost_complete_months
from projection.metrics.funnel import Filters, closed_deal_check, conversion_rates, stage_table
from projection.metrics.pta import REP_DIMENSIONS
from projection.periods import Month, is_recent, month_range, period_of
from ui import html as h
from ui.state import get_dataset, get_settings

SHORT = {"Live Transfer Successful": "Live Transfer", "Live Transfer Unsuccessful": "LT Unsuccessful",
         "Appointment Set": "Appt Set", "Appointment Held": "Appt Held", "Appointment Cancelled": "Appt Cancelled"}

ds = get_dataset()
if ds is None:
    st.stop()
settings = get_settings()

st.title("Funnel")
months = month_range(Month.of(ds.start), Month.of(ds.today))
quarters = list(dict.fromkeys(period_of(m, "quarter") for m in months))
periods = {q.key: (q.label + (" (To Date)" if q.end >= ds.today else ""), list(q.months)) for q in quarters}
periods |= {m.key: (m.label, [m]) for m in months}
done_q = [q.key for q in quarters if q.end < ds.today]
sources = sorted((set(ds.leads["source"]) | set(ds.revenues["source"])) - {""})

c = st.columns([2.4, 1.4, 2, 2, 2], vertical_alignment="bottom")
src = c[0].selectbox("Source", ["All Sources (Company)"] + sources, key="fun_src")
dim = c[1].segmented_control("Rep", ["ACQ", "FUS"], default="ACQ", key="fun_dim") or "ACQ"
col = REP_DIMENSIONS[dim].kpi_col
reps = sorted(set(ds.kpis[col]) - {""})
rep = c[2].selectbox(f"{dim} Rep", ["All"] + reps, key=f"fun_rep_{dim}")
pk = c[3].selectbox("Period", list(periods), index=list(periods).index(done_q[-1] if done_q else list(periods)[0]),
                    format_func=lambda k: periods[k][0], key="fun_period")
method = c[4].segmented_control("Conversion", ["period", "cohort"], default="period", key="fun_method",
                                format_func=lambda m: "Period Ratio" if m == "period" else "Cohort") or "period"
pmonths = [m for m in periods[pk][1] if m <= Month.of(ds.today)]
filters = Filters(sources=None if src.startswith("All") else (src,), rep_col=col if rep != "All" else None,
                  rep=rep if rep != "All" else None)
company = filters.sources is None and not filters.by_rep
cmonths = [m for m in pmonths if m in set(cost_complete_months(ds))]

if not cmonths:
    h.box("No completed cost month in this period yet, so cost and profit per stage are blank. Counts and "
          "conversions are live.", "warn")
if filters.by_rep:
    h.box("Rep filter on: costs aren't assigned to reps, so the cost and profit columns are hidden.", "info")
if method == "cohort":
    n_recent = int(settings.get("cohort_immature_months", 2))
    if is_recent(pmonths, ds.today, n_recent):
        h.box(f"<b>Recent cohort: still maturing.</b> These leads were created in the last {n_recent} months, so "
              "many haven't had time to reach later stages yet; conversions here will keep rising.", "warn")
    else:
        h.box("Cohort: leads created in this period, followed through every later stage.", "info")

table = stage_table(ds, pmonths, settings, filters, method).set_index("stage")
counts = table["count"]
top = counts["Lead"] or 1

left, right = st.columns(2)
with left, st.container(key="card-life"):
    rows = []
    for s in MAIN_PATH:
        n = int(counts[s])
        w = max(0.4, n / top * 100)
        inside = n / top > 0.8
        label_style = "left:10px;color:#fff" if inside else f"left:calc({w:.1f}% + 6px)"
        prev_txt = "" if s == "Lead" else f"<br>{h.pct(table.loc[s, 'from_previous'])} from prev."
        rows.append(f'<div class="frow"><span class="nm {"ind" if s == LIVE_TRANSFER else ""}">'
                    f'{"or " if s == LIVE_TRANSFER else ""}{h.esc(s)}</span><div class="ftrack">'
                    f'<i style="width:{w:.1f}%"></i><span style="{label_style}">{n:,}</span></div><span class="cv">'
                    f'{"100%" if s == "Lead" else h.pct(n / top) + " of leads"}{prev_txt}</span></div>')
    chips = "".join(f'<span class="chip">{h.esc(SHORT.get(s, s))} <b>{int(counts[s]):,}</b> · '
                    f'{h.pct(table.loc[s, "from_previous"])} of {h.esc(SHORT.get(PREVIOUS[s][0], PREVIOUS[s][0]))}'
                    "</span>" for s in LEAKAGE)
    chk = closed_deal_check(ds, pmonths, filters)
    note = (f"Closed Deal: GHL KPI count {chk.kpi_closed:,} vs REVENUES rows {chk.revenue_deals:,}"
            + (f" (gap {chk.gap:+,})" if chk.mismatch else " (match)")
            + ". Revenue and profit always come from REVENUES.")
    st.html(f'<div class="sh"><span class="t1">Lead Lifecycle</span><small>'
            f'{"events dated in this period" if method == "period" else "this period’s lead cohort"}</small></div>'
            f'<div class="funnel">{"".join(rows)}</div><div class="chips">{chips}</div><p class="status">{note}</p>')

with right, st.container(key="card-cvp"):
    st.html(f'<div class="sh"><span class="t1">Cost Vs Profit Per Stage</span><small>'
            f'{"company view" if company else "" if filters.by_rep else "this source"}</small></div>')
    if filters.by_rep or not cmonths:
        h.status("Hidden under a rep filter." if filters.by_rep else "Waiting for this period's costs to post.")
    else:
        rows = []
        mx = max([abs(v) for s in MAIN_PATH for v in (table.loc[s, "cost_per"], table.loc[s, "profit_per"])
                  if h.ok(v)] or [1]) or 1  # one scale for every row, so the bars compare across stages
        for s in MAIN_PATH:
            cp, pp = table.loc[s, "cost_per"], table.loc[s, "profit_per"]
            bars = (f'<div class="cvbar"><i style="width:{(abs(cp) if h.ok(cp) else 0) / mx * 100:.0f}%;'
                    f'background:var(--warn)"></i><i style="width:{(abs(pp) if h.ok(pp) else 0) / mx * 100:.0f}%;'
                    f'background:{"var(--good)" if not h.ok(pp) or pp >= 0 else "var(--bad)"}"></i></div>')
            rows.append([h.esc(SHORT.get(s, s)), h.money(cp), h.money(pp), f'<td class="l">{bars}</td>'])
        h.show(h.table(["Stage", "Mkt Cost / Stage" if company else "Cost / Stage", "Profit / Stage",
                        "Cost Vs Profit"], rows, left=(0, 3)))
        st.html('<div class="legend"><span><i style="background:var(--warn)"></i>Cost per stage</span><span>'
                '<i style="background:var(--good)"></i>Profit per stage (revenue − marketing cost)</span></div>')
        st.caption(f"Revenue, cost and profit use the cost-complete months: {', '.join(m.label for m in cmonths)}. "
                   "Closed Deal is per REVENUES deal." + (" Cohort: profit per stage isn't shown (the period's "
                                                          "revenue isn't the cohort's)." if method == "cohort" else ""))

h.heading("All Stages", None, "Marketing view = revenue − marketing cost; company view = revenue − all costs incl. "
          "payroll" if company else "" if filters.by_rep else "Source view = revenue − this source's marketing cost")
cols = ["Stage", "Count", "From Previous", "From Lead"]
cols += [] if filters.by_rep else ["Mkt Cost / Stage" if company else "Cost / Stage"]
cols += ["Revenue / Stage"] + ([] if filters.by_rep else ["Profit / Stage"])
cols += ["All-In Cost / Stage", "Net Profit / Stage"] if company else []
rows = []
for s, r in table.iterrows():
    cells = [h.esc(s) + (" " + h.pill("leak", "ins") if r["path"] == "leakage" else ""), h.num(r["count"]),
             "—" if s == "Lead" else h.pct(r["from_previous"]), h.pct(r["from_lead"])]
    if not filters.by_rep:
        cells.append(h.money(r["cost_per"]))
    cells.append(h.money(r["revenue_per"]))
    if not filters.by_rep:
        cells.append(h.money(r["profit_per"]))
    if company:
        cells += [h.money(r["all_in_cost_per"]), h.money(r["all_in_profit_per"])]
    rows.append(cells)
h.show(h.table(cols, rows))

h.heading("Conversion Matrix", None, "From stage (rows) to stage (columns). Only your listed pairs are filled; "
          "dashed cells involve Net Lead, which was added.")
rates = conversion_rates(ds, pmonths, filters, method).set_index(["from", "to"])["rate"]
froms = list(dict.fromkeys(a for a, _ in ALL_CONVERSIONS))
tos = [s for s in MAIN_PATH[1:] + LEAKAGE if any(b == s for _, b in ALL_CONVERSIONS)]
added = set(ADDED)
rows = []
for a in froms:
    cells = [f"<b>{h.esc(SHORT.get(a, a))}</b>"]
    for b in tos:
        if (a, b) not in rates.index:
            cells.append('<td class="mx-e"></td>')
            continue
        v = rates[(a, b)]
        alpha = round((min(1.0, v) ** 0.5) * 80) + 6 if h.ok(v) else 0
        style = f"background:color-mix(in srgb,var(--accent) {alpha}%,transparent);"
        style += "color:var(--on-accent);" if alpha > 55 else ""
        style += "outline:2px dashed var(--ovr);outline-offset:-3px;" if (a, b) in added else ""
        cells.append(f'<td style="{style}" title="{h.esc(a)} → {h.esc(b)}">{h.pct(v)}</td>')
    rows.append(cells)
h.show(h.table(["From \\ To", *[SHORT.get(s, s) for s in tos]], rows, cls="mx"))
if method == "period":
    h.status("Period ratios compare two counts of events dated in the same period, so they can pass 100% (for example "
             "when deals close from offers made earlier). Switch to Cohort to follow the same leads through.")
