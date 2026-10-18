"""Projections: one quarter's costs and revenue, projected vs actual, saved as revisions in the app database."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from projection.data.schema import KNOWN_EXITS, block_of
from projection.metrics.core import cost_complete_months, marketing_names
from projection.metrics.follow_up import UNPROJECTED
from projection.metrics.pacing import cost_pace, daily_pace
from projection.metrics.quarter import QuarterView, quarter_view
from projection.model import BLOCKS, FOLLOW_UP, QuarterProjection
from projection.periods import Month, period_of
from projection.planning import (
    BLOCK_LABELS,
    add_actual_lines,
    add_revenue_line,
    add_source,
    copy_lines,
    follow_up_sources,
    monthly_costs,
    monthly_revenue,
    new_projection,
    other_marketing,
    previous_quarter,
    quarter_options,
    reconcile,
)
from projection.suggest.lookback import LOOKBACKS
from projection.suggest.marketing import reverse
from projection.suggest.profit_target import fixed_parts, needed_contribution, plan_a, plan_b, source_economics
from projection.suggest.quarter import (
    accept_budget,
    accept_revenue,
    budget_drift,
    mark_typed,
    quarter_suggestions,
)
from ui.state import get_dataset, get_settings, get_store

MONEY = st.column_config.NumberColumn(format="dollar")
PCT = st.column_config.NumberColumn(format="percent")
COUNT = st.column_config.NumberColumn(format="%.1f")
ORIGIN = {"manual": "", "accepted_suggestion": "✓ Suggested", "override": "🟠 Override"}
NAN = float("nan")


def num(x: float | None) -> float:
    return NAN if x is None else x


def usd(x: float, decimals: int = 0) -> str:
    """Dollar amount for markdown text (a bare $ starts math formatting)."""
    return f"\\${x:,.{decimals}f}"


ds = get_dataset()
if ds is None:
    st.stop()
settings = get_settings()
store = get_store()
state = st.session_state.setdefault("projections", {"drafts": {}, "rev": {}, "dirty": {}, "ver": {}})


# ---------- draft handling
def load(qid: str, revision: dict | None = None) -> None:
    rev = revision or store.latest_revision(qid)
    state["drafts"][qid] = rev["payload"] if rev else new_projection(qid, settings).model_dump()
    state["rev"][qid] = rev["id"] if rev else None
    state["dirty"][qid] = False
    state["ver"][qid] = state["ver"].get(qid, 0) + 1


def draft(qid: str) -> QuarterProjection:
    if qid not in state["drafts"]:
        load(qid)
    return QuarterProjection.model_validate(state["drafts"][qid])


def put(p: QuarterProjection) -> None:
    state["drafts"][p.quarter_id] = p.model_dump()
    state["dirty"][p.quarter_id] = True
    state["ver"][p.quarter_id] = state["ver"].get(p.quarter_id, 0) + 1  # fresh editors after every change


def apply_edits(qid: str, key: str, group: str, indices: list[int], fields: dict[str, str],
                suggestions: dict[int, object] | None = None) -> None:
    """data_editor on_change: copy edited cells onto the draft's lines, apply ticked Accept, drop ticked Remove."""
    p = draft(qid)
    lines = getattr(p, group)
    drop = set()
    for row, changes in st.session_state[key]["edited_rows"].items():
        i = indices[int(row)]
        line = lines[i]
        for col, value in changes.items():
            if col == "Remove" and value:
                drop.add(i)
            elif col in fields:
                setattr(line, fields[col], float(value or 0))
                mark_typed(line)
        if changes.get("Accept") and suggestions and suggestions.get(i) is not None:
            (accept_revenue if group == "revenue" else accept_budget)(line, suggestions[i])
    setattr(p, group, [x for i, x in enumerate(lines) if i not in drop])
    put(p)


def accept_all(qid: str, group: str, suggestions: dict[int, object]) -> None:
    """Fill every empty or previously accepted line; typed values (manual or override) always win."""
    p = draft(qid)
    lines = getattr(p, group)
    for i, s in suggestions.items():
        line = lines[i]
        empty = (line.p_cost == 0) if group != "revenue" else (line.p_deals == 0 and line.p_avg == 0)
        if s is not None and (empty or line.origin == "accepted_suggestion"):
            (accept_revenue if group == "revenue" else accept_budget)(line, s)
    put(p)


def set_lookback(qid: str, key: str) -> None:
    p = draft(qid)
    p.lookback = st.session_state[key] or p.lookback
    put(p)


def set_custom(qid: str, key: str, field: str) -> None:
    p = draft(qid)
    setattr(p, field, st.session_state[key])
    put(p)


def set_target(qid: str, key: str) -> None:
    p = draft(qid)
    p.profit_target = st.session_state[key]
    put(p)


def usd_text(text: str) -> str:
    return text.replace("$", "\\$")


def flag_text(s, drift: float | None = None) -> str:
    if s is None:
        return ""
    notes = []
    if getattr(s, "flags", None) is not None:
        f = s.flags
        notes += [n for n, on in (("⛔ Insufficient Data", f.insufficient), ("⚠️ Low Confidence", f.low_confidence),
                                  ("📈 Over Scale Cap", f.scale)) if on]
    if drift is not None:
        notes.append(f"🔄 Now ${drift:,.0f}")
    return " · ".join(notes)


def user() -> str:
    try:
        return st.user.email or ""
    except Exception:
        return ""


# ---------- header
options = quarter_options(ds.start, ds.today)
current = period_of(Month.of(ds.today), "quarter").key
keys = [p.key for p in options]
st.title("Projections")
top = st.columns([2, 5], vertical_alignment="bottom")
qid = top[0].selectbox("Quarter", keys, index=keys.index(current) if current in keys else len(keys) - 1,
                       format_func=lambda k: next(p.label for p in options if p.key == k))
period = next(p for p in options if p.key == qid)
proj = draft(qid)
view: QuarterView = quarter_view(ds, proj, period, settings)
sug = quarter_suggestions(ds, proj, period, settings)
ver = state["ver"][qid]

rev_id = state["rev"].get(qid)
saved = store.get_revision(rev_id) if rev_id else None
status = (f"Revision #{rev_id} · saved {saved['saved_at']:%b %-d, %Y %-I:%M %p}"
          + (f" by {saved['saved_by']}" if saved and saved["saved_by"] else "")) if saved else "Not saved yet"
top[1].caption(status + ("  ·  **Unsaved changes**" if state["dirty"].get(qid) else ""))

# ---------- summary
rec = reconcile(ds, view)
m = st.columns(5)
in_progress = period.start <= ds.today <= period.end
pva = view.p_cost - view.a_cost
rev_pace = daily_pace(period, ds.today, view.p_revenue, view.a_revenue)
gap = view.a_revenue - (rev_pace.expected_to_date if in_progress else view.p_revenue)
m[0].metric("Revenue", f"${view.a_revenue:,.0f}",
            f"{'+' if gap >= 0 else '-'}${abs(gap):,.0f} vs {'expected by now' if in_progress else 'projected'}",
            help=f"Projected {usd(view.p_revenue)} for the quarter. Actual runs to today.")
cost_delta = f"+${pva:,.0f} under budget" if pva >= 0 else f"-${-pva:,.0f} over budget"
m[1].metric("Costs", f"${view.a_cost:,.0f}", cost_delta if view.complete else view.costs_label,
            delta_color="normal" if view.complete else "off",
            help=f"Projected {usd(view.p_cost)}. Actual covers {view.costs_label}.")
m[2].metric("Profit", f"${view.a_profit:,.0f}", f"projected ${view.p_profit:,.0f}", delta_color="off",
            help=f"Revenue − costs over the cost-complete months ({view.costs_label}).")
m[3].metric("Margin", f"{view.a_margin:.1%}" if view.a_margin is not None else "—",
            f"projected {view.p_margin:.1%}" if view.p_margin is not None else None, delta_color="off")
m[4].metric("Cost %", f"{view.a_pct:.1%}" if view.a_pct is not None else "—",
            f"projected {view.p_pct:.1%}" if view.p_pct is not None else None, delta_color="off",
            help="Costs ÷ revenue excluding " + ", ".join(settings.get("pct_base_excluded_exits", [])) + ".")

if in_progress:
    rp = rev_pace
    cp = cost_pace(period, view.cost_months, view.p_cost, view.a_cost)
    st.info(f"**Pacing** · Revenue {usd(rp.actual)} vs {usd(rp.expected_to_date)} expected by now ({rp.basis}); "
            f"end-of-quarter forecast {usd(rp.forecast)}. Costs {usd(cp.actual)} vs {usd(cp.expected_to_date)} "
            f"({cp.basis}); forecast {usd(cp.forecast)}.", icon=":material/speed:")
if rec.ok:
    st.caption(f":material/check_circle: Lines add up to the sheet: costs {usd(rec.sheet_cost, 2)} "
               f"({view.costs_label}), revenue {usd(rec.sheet_revenue, 2)} from {rec.sheet_deals} deals.")
else:
    st.error(f"Lines don't add up to the sheet: costs {usd(rec.lines_cost, 2)} vs {usd(rec.sheet_cost, 2)}, "
             f"revenue {usd(rec.lines_revenue, 2)} vs {usd(rec.sheet_revenue, 2)}, "
             f"deals {rec.lines_deals} vs {rec.sheet_deals}.")

# ---------- actions
a = st.columns([1.1, 1.1, 1.5, 2, 2.6], vertical_alignment="bottom")
note = a[4].text_input("Note", placeholder="What changed (optional)", label_visibility="collapsed")
if a[0].button("Save", type="primary", icon=":material/save:", disabled=not state["dirty"].get(qid),
               width="stretch"):
    new_id = store.save_revision(qid, proj.model_dump(), by=user(), note=note)
    load(qid, store.get_revision(new_id))
    st.toast(f"Saved revision #{new_id}", icon=":material/check:")
    st.rerun()
if a[1].button("Discard", icon=":material/undo:", disabled=not state["dirty"].get(qid), width="stretch"):
    load(qid)
    st.rerun()
prev_id = previous_quarter(qid)
prev = store.latest_revision(prev_id)
if a[2].button(f"Copy {prev_id.replace('-', ' ')}", icon=":material/content_copy:", disabled=prev is None,
               width="stretch", help="Start from the previous quarter's saved lines and values."):
    put(copy_lines(QuarterProjection.model_validate(prev["payload"]), qid))
    st.rerun()
if a[3].button("Add Lines For Actuals", icon=":material/playlist_add:", width="stretch",
               help="Add a line for every source with spend or deals this quarter (projected values stay 0)."):
    put(add_actual_lines(proj, ds, period, settings))
    st.rerun()

# ---------- suggestion window
b = st.columns([5, 1.6, 1.6, 2.8], vertical_alignment="bottom")
lb_key = f"lookback_{qid}_{ver}"
b[0].segmented_control("Suggestions Learn From", list(LOOKBACKS), default=proj.lookback, key=lb_key,
                       format_func=LOOKBACKS.get, on_change=set_lookback, args=(qid, lb_key))
if proj.lookback == "custom":
    before = [m.key for m in cost_complete_months(ds) if m.last_day < period.start]
    if before:
        for col, field, label, default in ((b[1], "lookback_from", "From", before[0]),
                                           (b[2], "lookback_to", "To", before[-1])):
            k = f"{field}_{qid}_{ver}"
            value = getattr(proj, field) if getattr(proj, field) in before else default
            col.selectbox(label, before, index=before.index(value), key=k,
                          format_func=lambda x: Month.from_key(x).label, on_change=set_custom, args=(qid, k, field))
        if not (proj.lookback_from and proj.lookback_to):
            proj.lookback_from, proj.lookback_to = before[0], before[-1]
            put(proj)
            st.rerun()
b[3].caption(f":material/insights: Suggestions use **{sug.window}** (whole months with costs, before this quarter)."
             if sug.months else ":material/block: No complete months before this quarter, so no suggestions.")


# ---------- costs
def cost_editor(group: str, title: str) -> dict[int, object]:
    lines = getattr(proj, group)
    actual = {c.source: c for c in view.costs}
    marketing = group == "marketing"
    suggestions = {i: sug.budgets.get(c.source) for i, c in enumerate(lines)} if marketing else {}
    rows = []
    for i, c in enumerate(lines):
        x = actual[c.source]
        row = {"Remove": False, "Source": c.source, "P.Cost": c.p_cost}
        if marketing:
            s = suggestions[i]
            r = reverse(c.p_cost, s.cost, s.leads, s.deals, s.net_leads) if s and c.p_cost else None
            row |= {"Suggested": num(s.budget if s else None), "Accept": False,
                    "Implied Leads": num(r.implied_leads if r else None),
                    "Implied Deals": num(r.implied_deals if r else None),
                    "Notes": flag_text(s, budget_drift(c, s))}
        row |= {"A.Cost": x.a_cost, "PVA": x.pva_cost, "P.%": num(x.p_pct), "A.%": num(x.a_pct),
                "PVA.%": num(x.pva_pct), "Origin": ORIGIN[c.origin]}
        rows.append(row)
    st.markdown(f"**{title}**")
    if not rows:
        st.caption("No lines yet. Add a source below.")
        return suggestions
    key = f"cost_{group}_{qid}_{ver}"
    st.data_editor(
        pd.DataFrame(rows), key=key, hide_index=True, width="stretch",
        disabled=["Source", "Suggested", "Implied Leads", "Implied Deals", "Notes", "A.Cost", "PVA", "P.%", "A.%",
                  "PVA.%", "Origin"],
        column_config={"Remove": st.column_config.CheckboxColumn(width="small"), "P.Cost": MONEY, "A.Cost": MONEY,
                       "Suggested": st.column_config.NumberColumn(
                           format="dollar", help="Target deals × cost per deal over the suggestion window"),
                       "Accept": st.column_config.CheckboxColumn(width="small", help="Use the suggested budget"),
                       "Implied Leads": st.column_config.NumberColumn(format="%.0f", help="P.Cost ÷ CPL"),
                       "Implied Deals": st.column_config.NumberColumn(format="%.1f", help="Implied leads ÷ LPD"),
                       "PVA": MONEY, "P.%": PCT, "A.%": PCT, "PVA.%": PCT},
        on_change=apply_edits, args=(qid, key, group, list(range(len(lines))), {"P.Cost": "p_cost"}, suggestions))
    return suggestions


st.subheader("Costs")
st.caption(f"Actual costs cover {view.costs_label}. PVA = projected − actual: positive is under budget.")
mkt_sug = cost_editor("marketing", "Marketing")
if proj.marketing:
    c1, c2 = st.columns([1, 3], vertical_alignment="center")
    c1.button("Accept All Budgets", icon=":material/done_all:", key=f"acc_mkt_{qid}_{ver}",
              on_click=accept_all, args=(qid, "marketing", mkt_sug),
              help="Fills empty or previously accepted lines. Typed values are never replaced.")
    with c2.expander("How The Suggested Budgets Are Worked Out", icon=":material/function:"):
        st.caption("Budget = target deals × leads per deal × CPL = target deals × cost per deal. Target deals = the "
                   "source's P.Deals across all its revenue lines, so set revenue deals first.")
        for c in proj.marketing:
            s = sug.budgets.get(c.source)
            if s:
                st.markdown(f"**{c.source}**\n" + "\n".join(f"- {usd_text(line)}" for line in s.explain()))
other = other_marketing(view)
oc = next(c for c in view.costs if c.kind == "other_marketing")
with st.expander(f"Other Marketing (Unprojected) · {usd(oc.a_cost, 2)}", icon=":material/campaign:"):
    if other:
        st.dataframe(pd.Series(other, name="A.Cost").sort_values(ascending=False).to_frame(),
                     column_config={"A.Cost": MONEY})
    else:
        st.caption("All marketing spend this quarter is on a projected line.")
cost_editor("non_marketing", "Non-Marketing")
extra_non = [c for c in view.costs if c.kind == "non_marketing" and c.source not in
             {x.source for x in proj.non_marketing}]
if extra_non:
    st.warning("Non-marketing spend not on the projection: "
               + ", ".join(f"{c.source} {usd(c.a_cost, 2)}" for c in extra_non), icon=":material/info:")

with st.popover("Add Source", icon=":material/add:"):
    mkt = marketing_names(ds, settings)
    on = {c.source for c in proj.marketing + proj.non_marketing}
    choices = sorted(mkt - on)
    pick = st.selectbox("From the sheet", ["—"] + choices, key=f"add_src_{qid}")
    typed = st.text_input("Or type a name", key=f"add_src_typed_{qid}",
                          help="Must match the COSTS / KPIs / REVENUES Source exactly to pick up actuals.")
    kind = st.segmented_control("Type", ["Marketing", "Non-Marketing"], default="Marketing", key=f"add_kind_{qid}")
    name = typed.strip() or (pick if pick != "—" else "")
    if st.button("Add", disabled=not name, key=f"add_src_btn_{qid}"):
        put(add_source(proj, name, marketing=kind != "Non-Marketing"))
        st.rerun()

# ---------- revenue
st.subheader("Revenue")
rev_sug: dict[int, object] = {}
actual_rev = {(x.block, x.source, x.exit): x for x in view.revenue if x.kind != UNPROJECTED}
for block in BLOCKS:
    st.markdown(f"**{BLOCK_LABELS[block]}**")
    idx = [i for i, r in enumerate(proj.revenue) if r.block == block]
    rows = []
    for i in idx:
        r = proj.revenue[i]
        x = actual_rev.get((r.block, r.source, r.exit))
        s = sug.revenue.get((r.block, r.source, r.exit))
        rev_sug[i] = s
        rows.append({"Remove": False, "Source": r.source, "Exit": r.exit, "P.Deals": r.p_deals, "P.Avg": r.p_avg,
                     "Sugg. Deals": num(s.p_deals if s else None), "Sugg. Avg": num(s.p_avg if s else None),
                     "Accept": False, "P.Revenue": r.p_revenue, "A.Deals": x.a_deals if x else 0,
                     "A.Avg": num(x.a_avg if x else None), "A.Revenue": x.a_revenue if x else 0.0,
                     "PVA Revenue": (x.a_revenue if x else 0) - r.p_revenue, "Origin": ORIGIN[r.origin]})
    if rows:
        key = f"rev_{block}_{qid}_{ver}"
        st.data_editor(
            pd.DataFrame(rows), key=key, hide_index=True, width="stretch",
            disabled=["Source", "Exit", "Sugg. Deals", "Sugg. Avg", "P.Revenue", "A.Deals", "A.Avg", "A.Revenue",
                      "PVA Revenue", "Origin"],
            column_config={"Remove": st.column_config.CheckboxColumn(width="small"), "P.Deals": COUNT,
                           "P.Avg": MONEY, "Sugg. Deals": st.column_config.NumberColumn(
                               format="%.2f", help="Deals in the window ÷ quarters in the window"),
                           "Sugg. Avg": st.column_config.NumberColumn(format="dollar", help="Window revenue ÷ deals"),
                           "Accept": st.column_config.CheckboxColumn(width="small", help="Use both suggested values"),
                           "P.Revenue": MONEY, "A.Avg": MONEY, "A.Revenue": MONEY, "PVA Revenue": MONEY},
            on_change=apply_edits,
            args=(qid, key, "revenue", idx, {"P.Deals": "p_deals", "P.Avg": "p_avg"}, {i: rev_sug[i] for i in idx}))
    projected = {(r.block, r.source, r.exit) for r in proj.revenue}
    loose = [x for x in view.revenue if x.block == block and (x.block, x.source, x.exit) not in projected]
    if loose:
        st.caption("Actuals without a projected line (they still count in the totals):")
        st.dataframe(pd.DataFrame([{"Source": x.label, "Exit": x.exit, "A.Deals": x.a_deals, "A.Avg": x.a_avg,
                                    "A.Revenue": x.a_revenue} for x in loose]),
                     hide_index=True, width="stretch", column_config={"A.Avg": MONEY, "A.Revenue": MONEY})
    fu = follow_up_sources(view, block)
    if len(fu):
        with st.expander(f"Follow Up Sources · {BLOCK_LABELS[block]}", icon=":material/call_split:"):
            st.caption("Sources with no line in this block roll into Follow Up.")
            st.dataframe(fu, hide_index=True, width="stretch", column_config={"revenue": MONEY})
    if not rows and not loose:
        st.caption("No lines and no deals yet.")

if proj.revenue:
    c1, c2 = st.columns([1, 3], vertical_alignment="center")
    c1.button("Accept All Revenue", icon=":material/done_all:", key=f"acc_rev_{qid}_{ver}",
              on_click=accept_all, args=(qid, "revenue", rev_sug),
              help="Fills empty or previously accepted lines. Typed values are never replaced.")
    with c2.expander("How The Suggested Revenue Is Worked Out", icon=":material/function:"):
        st.caption("P.Deals = deals in the window ÷ quarters in the window; P.Avg = window revenue ÷ window deals. "
                   "Follow Up pools the sources that have no line in that block.")
        for (blk, src, ex), s in sug.revenue.items():
            pd_txt = f"{s.p_deals:.2f}" if s.p_deals is not None else "—"
            avg_txt = usd(s.p_avg, 2) if s.p_avg is not None else "no deals"
            st.markdown(f"- **{src} · {ex}** ({BLOCK_LABELS[blk]}): {s.deals} deals over {s.quarters:g} quarter(s) "
                        f"→ {pd_txt} per quarter; avg {avg_txt}"
                        + (f" · from {', '.join(s.sources)}" if src == FOLLOW_UP and s.sources else ""))

with st.popover("Add Revenue Line", icon=":material/add:"):
    block = st.selectbox("Block", BLOCKS, format_func=BLOCK_LABELS.get, key=f"add_rev_block_{qid}")
    exits = [e for e in KNOWN_EXITS if block_of(e) == block]
    sources = sorted({c.source for c in proj.marketing} | set(ds.revenues["source"]) - {""}) + [FOLLOW_UP]
    src = st.selectbox("Source", sources, key=f"add_rev_src_{qid}")
    ex = st.selectbox("Exit Strategy", exits, key=f"add_rev_exit_{qid}")
    if st.button("Add", key=f"add_rev_btn_{qid}"):
        put(add_revenue_line(proj, block, src, ex))
        st.rerun()

# ---------- profit target (D3)
st.subheader("Profit Target")
t_key = f"target_{qid}_{ver}"
tc = st.columns([1, 3], vertical_alignment="bottom")
tc[0].number_input("Target Profit For The Quarter", min_value=0.0, step=10000.0, format="%.0f",
                   value=proj.profit_target, key=t_key, on_change=set_target, args=(qid, t_key),
                   placeholder="e.g. 400000")
if proj.profit_target is None:
    tc[1].caption("Enter a target to see how many marketing deals, and what budget, it would take.")
elif not sug.months:
    tc[1].caption("No history window before this quarter, so plans can't be worked out.")
else:
    fixed_costs, fixed_revenue = fixed_parts(proj)
    needed = needed_contribution(proj.profit_target, fixed_costs, fixed_revenue)
    tc[1].markdown(f"Needed from marketing sources: **{usd(needed)}** = target {usd(proj.profit_target)} "
                   f"+ non-marketing costs {usd(fixed_costs)} − fixed revenue {usd(fixed_revenue)} "
                   "(Follow Up, Fix & Flip, Buy & Hold as projected).")
    econ = source_economics(ds, proj, sug.months, settings)
    pc = st.columns(2)
    for col, plan in zip(pc, (plan_a(needed, econ), plan_b(needed, econ)), strict=True):
        with col:
            st.markdown(f"**Plan {plan.name}**")
            if plan.lines:
                st.dataframe(pd.DataFrame([{"Source": x.source, "Deals": x.deals, "Budget": x.budget,
                                            "Contribution": x.contribution, "Over Cap": "📈" if x.over_cap else ""}
                                           for x in plan.lines]),
                             hide_index=True, width="stretch",
                             column_config={"Deals": COUNT, "Budget": MONEY, "Contribution": MONEY})
            st.caption(f"Budget {usd(plan.budget)}"
                       + (f" · factor k = {plan.k:.2f}" if plan.k is not None else "")
                       + (f" · **shortfall {usd(plan.shortfall)}**" if plan.shortfall > 0.5 else " · target met"))
    with st.expander("Source Economics Used", icon=":material/function:"):
        st.caption(f"From {sug.window}. Contribution per deal = avg main-block deal size − cost per deal. "
                   f"Cap = {settings.get('scale_cap', 1.5):g}× the best quarter's spend ÷ cost per deal.")
        st.dataframe(pd.DataFrame([{"Source": e.source, "Cost Per Deal": num(e.cost_per_deal),
                                    "Avg Deal": num(e.avg_deal), "Contribution": num(e.contribution),
                                    "Projected Main Deals": e.projected_deals, "Max Deals": e.max_deals}
                                   for e in econ]),
                     hide_index=True, width="stretch",
                     column_config={"Cost Per Deal": MONEY, "Avg Deal": MONEY, "Contribution": MONEY,
                                    "Projected Main Deals": COUNT, "Max Deals": COUNT})

# ---------- month by month and history
with st.expander("Month By Month", icon=":material/calendar_month:"):
    st.markdown("**Costs**")
    st.dataframe(monthly_costs(ds, period), width="stretch",
                 column_config={c: MONEY for c in [*(m.label for m in period.months), "Total"]})
    st.markdown("**Revenue**")
    mr = monthly_revenue(ds, period)
    st.dataframe(mr, width="stretch", column_config={c: MONEY for c in mr.columns if "revenue" in c})

with st.expander("History", icon=":material/history:"):
    revs = store.list_revisions(qid)
    if not revs:
        st.caption("Nothing saved for this quarter yet.")
    else:
        st.dataframe(pd.DataFrame([{"Revision": r["id"], "Saved": f"{r['saved_at']:%b %-d, %Y %-I:%M %p}",
                                    "By": r["saved_by"], "Note": r["note"]} for r in revs]),
                     hide_index=True, width="stretch")
        pick = st.selectbox("Open a revision", [r["id"] for r in revs], format_func=lambda i: f"#{i}",
                            key=f"hist_{qid}")
        if st.button("Open", key=f"hist_open_{qid}", help="Loads it as the working copy; save to make it current."):
            load(qid, store.get_revision(pick))
            state["dirty"][qid] = pick != revs[0]["id"]
            st.rerun()
st.caption(f"Data refreshed {ds.fetched_at:%b %-d, %Y %-I:%M %p} · today {ds.today:%b %-d, %Y}")
