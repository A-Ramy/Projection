"""Projections: build a quarter on its backbone (the quarter before, by default). Every source starts at the
backbone's actuals; type spend, revenue or deals per source and the rest is worked out; place the deals on exit
rows; non-marketing costs are typed. Saved as revisions in the app database (never in the sheet)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from projection.data.schema import KNOWN_EXITS, block_of
from projection.metrics.core import in_months, marketing_names
from projection.metrics.follow_up import UNPROJECTED
from projection.metrics.pacing import cost_pace, daily_pace
from projection.metrics.quarter import QuarterView, quarter_view
from projection.model import FOLLOW_UP, QuarterProjection
from projection.periods import Month, Period, elapsed_days, period_of
from projection.plan import (
    FOLLOW_UP_KIND,
    NO_COST,
    backbone,
    prefill,
    set_driver,
    source_rows,
    split_by_mix,
    sync_costs,
    totals,
    use_plan,
)
from projection.planning import (
    BLOCK_LABELS,
    add_revenue_line,
    add_source,
    new_projection,
    quarter_options,
    reconcile,
    scale_projection,
)
from projection.suggest.profit_target import fixed_parts, needed_contribution, plan_a, plan_b, source_economics
from ui import html as h
from ui.state import get_dataset, get_settings, get_store

MONEY = st.column_config.NumberColumn(format="dollar")
COUNT = st.column_config.NumberColumn(format="%.2f")
NAN = float("nan")
SET_BY = {"spend": "Spend", "revenue": "Revenue", "deals": "Deals", "exits": "Exit Rows"}
KIND = {"marketing": "Marketing", NO_COST: "No Cost", FOLLOW_UP_KIND: "Follow Up"}
BACKBONES = {"last_quarter": "Last Quarter", "last_2_quarters": "Last 2 Quarters", "all": "All Since Start",
             "custom": "Custom"}


def num(x: float | None) -> float:
    return NAN if x is None else x


ds = get_dataset()
if ds is None:
    st.stop()
settings = get_settings()
store = get_store()
state = st.session_state.setdefault("projections", {"drafts": {}, "rev": {}, "dirty": {}, "ver": {}})
payroll = set(settings.get("payroll", []))
options = quarter_options(ds.start, ds.today)
by_key = {p.key: p for p in options}
current = period_of(Month.of(ds.today), "quarter").key


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


def is_empty(p: QuarterProjection) -> bool:
    return not p.marketing and not p.revenue and not p.drivers


def edit_sources(qid: str, key: str, names: list[str]) -> None:
    """Sources table: the last of Spend / Revenue / Deals you typed becomes that source's driver."""
    p = draft(qid)
    bb = backbone(ds, p, by_key[qid])
    drop = set()
    for row, changes in st.session_state[key]["edited_rows"].items():
        src = names[int(row)]
        if changes.get("Remove"):
            drop.add(src)
            continue
        for col, kind in (("Spend", "spend"), ("Revenue", "revenue"), ("Deals", "deals")):
            if col in changes and changes[col] is not None:
                if kind == "spend" and src == FOLLOW_UP:
                    continue  # Follow Up has no spend: project it by revenue or deals
                set_driver(p, src, kind, changes[col], bb, settings)
        if changes.get("Use Exit Rows"):
            set_driver(p, src, "exits", 0, bb, settings)
    if drop:
        p.marketing = [c for c in p.marketing if c.source not in drop]
        p.revenue = [r for r in p.revenue if r.source not in drop]
        p.drivers = {k: v for k, v in p.drivers.items() if k not in drop}
    put(p)


def edit_exits(qid: str, key: str) -> None:
    p = draft(qid)
    drop = set()
    for row, changes in st.session_state[key]["edited_rows"].items():
        line = p.revenue[int(row)]
        if changes.get("Remove"):
            drop.add(int(row))
            continue
        if "P.Avg" in changes:
            line.p_avg = float(changes["P.Avg"] or 0)
        if "P.Deals" in changes:
            line.p_deals = float(changes["P.Deals"] or 0)
        if "P.Revenue" in changes and line.p_avg:
            line.p_deals = round(float(changes["P.Revenue"] or 0) / line.p_avg, 2)
    p.revenue = [r for i, r in enumerate(p.revenue) if i not in drop]
    sync_costs(p, backbone(ds, p, by_key[qid]), settings)
    put(p)


def edit_costs(qid: str, key: str) -> None:
    p = draft(qid)
    for row, changes in st.session_state[key]["edited_rows"].items():
        if "P.Cost" in changes:
            p.non_marketing[int(row)].p_cost = float(changes["P.Cost"] or 0)
    put(p)


def set_field(qid: str, key: str, field: str, mapper=None) -> None:
    p = draft(qid)
    value = st.session_state[key]
    if value is None:
        return
    setattr(p, field, mapper(value) if mapper else value)
    if field.startswith("lookback"):
        sync_costs(p, backbone(ds, p, by_key[qid]), settings)
    put(p)


def user() -> str:
    try:
        return st.user.email or ""
    except Exception:
        return ""


def quarter_label(k: str) -> str:
    tag = " · Live" if k == current else (" · Done" if by_key[k].end < ds.today else " · Next")
    return by_key[k].label.replace(" 20", " '") + tag


# ---------- header: click-only controls
st.title("Projections")
keys = list(by_key)
qid = st.segmented_control("Quarter", keys, default=current if current in keys else keys[-1], key="proj_quarter",
                           format_func=quarter_label) or current
period = by_key[qid]
proj = draft(qid)
ver = state["ver"][qid]
c = st.columns([3.2, 3.6], vertical_alignment="bottom")
lb_key = f"lookback_{qid}_{ver}"
c[0].segmented_control("Backbone (Actuals The Projection Is Built On)", list(BACKBONES), default=proj.lookback,
                       format_func=BACKBONES.get, key=lb_key, on_change=set_field, args=(qid, lb_key, "lookback"))
show = c[1].segmented_control("Show", ["quarter"] + [m.key for m in period.months], default="quarter",
                              key=f"show_{qid}", format_func=lambda k: "Whole Quarter" if k == "quarter"
                              else Month.from_key(k).label[:3]) or "quarter"
before = [m for m in backbone(ds, proj, period).longer]
if proj.lookback == "custom" and before:
    rk = f"range_{qid}_{ver}"
    lo = Month.from_key(proj.lookback_from) if proj.lookback_from else before[0]
    hi = Month.from_key(proj.lookback_to) if proj.lookback_to else before[-1]
    lo, hi = (lo if lo in before else before[0]), (hi if hi in before else before[-1])
    st.select_slider("Backbone Months", options=before, value=(lo, hi), format_func=lambda m: m.label, key=rk,
                     on_change=lambda: (set_field(qid, rk, "lookback_from", lambda v: v[0].key),
                                        set_field(qid, rk, "lookback_to", lambda v: v[1].key)))
    if not (proj.lookback_from and proj.lookback_to):
        proj.lookback_from, proj.lookback_to = lo.key, hi.key
        put(proj)
        st.rerun()

bb = backbone(ds, proj, period)
if is_empty(proj) and bb.months and store.latest_revision(qid) is None:
    proj = prefill(ds, period, settings, proj)  # a new quarter starts as the backbone repeated
    put(proj)
    st.rerun()

rev_id = state["rev"].get(qid)
saved = store.get_revision(rev_id) if rev_id else None
saved_txt = (f"Saved version #{rev_id}, {saved['saved_at']:%b %-d, %-I:%M %p}"
             + (f" by {h.esc(saved['saved_by'])}" if saved["saved_by"] else "")) if saved else "Not saved yet"
dirty = " · <b>Unsaved changes</b>" if state["dirty"].get(qid) else ""
when = ("Complete: actuals are final." if period.end < ds.today else
        f"In progress: revenue to {ds.today:%b %-d}, costs post at month end." if period.start <= ds.today else
        "Future quarter.")
h.status(f"{when} · Backbone: <b>{bb.label}</b> actuals{' per quarter' if bb.quarters > 1 else ''} · "
         f"{saved_txt}{dirty}")
if not bb.months:
    h.box("No complete months before this quarter, so there's no backbone: type every number yourself.", "warn")
elif not saved:
    h.box(f"Pre-filled with the {bb.label} actuals. Change what you plan to do differently, then <b>Save</b> "
          "(save at the start of the quarter; every version is kept).", "info")

# ---------- actions
a = st.columns([1.1, 1.1, 1.8, 3.4], vertical_alignment="bottom")
note = a[3].text_input("Note", placeholder="What changed (optional)", label_visibility="collapsed")
if a[0].button("Save", type="primary", icon=":material/save:", disabled=not state["dirty"].get(qid), width="stretch"):
    new_id = store.save_revision(qid, proj.model_dump(), by=user(), note=note)
    load(qid, store.get_revision(new_id))
    st.toast(f"Saved version #{new_id}", icon=":material/check:")
    st.rerun()
if a[1].button("Discard", icon=":material/undo:", disabled=not state["dirty"].get(qid), width="stretch"):
    load(qid)
    st.rerun()
if a[2].button("Reset To Backbone", icon=":material/restart_alt:", width="stretch", disabled=not bb.months,
               help=f"Start again from the {bb.label} actuals (your typed numbers are cleared until you save)."):
    put(prefill(ds, period, settings, proj))
    st.rerun()

edit = show == "quarter"
if edit:
    shown, shown_proj = period, proj
else:
    m = Month.from_key(show)
    shown, shown_proj = Period("month", m.key, m.label, (m,)), scale_projection(proj, 1 / 3)
view: QuarterView = quarter_view(ds, shown_proj, shown, settings)
rows = source_rows(proj, bb, settings)
tot = totals(proj, rows)
scale = 1 if edit else 1 / 3
b_c, b_r = in_months(ds.costs, bb.months), in_months(ds.revenues, bb.months)
q = bb.quarters or 1
backbone_tot = {"revenue": float(b_r["revenue"].sum()) / q, "cost": float(b_c["cost"].sum()) / q,
                "deals": len(b_r) / q}
backbone_tot["profit"] = backbone_tot["revenue"] - backbone_tot["cost"]

# ---------- summary
in_progress = shown.start <= ds.today <= shown.end
p_rev, p_cost, p_profit = tot["revenue"] * scale, tot["cost"] * scale, tot["profit"] * scale
tiles = [("Projected Profit", h.money(p_profit), f"Revenue {h.money(p_rev)} − cost {h.money(p_cost)}<br>Margin "
          f"{h.pct(p_profit / p_rev if p_rev else None)} · {h.num(tot['deals'] * scale)} deals"),
         (f"Backbone · {bb.label}", h.money(backbone_tot["profit"] * scale),
          f"Revenue {h.money(backbone_tot['revenue'] * scale)} − cost {h.money(backbone_tot['cost'] * scale)}"
          f"<br>{h.num(backbone_tot['deals'] * scale)} deals{' (per quarter)' if bb.quarters > 1 else ''}")]
if in_progress:
    rp = daily_pace(shown, ds.today, p_rev, view.a_revenue)
    cp = cost_pace(shown, view.cost_months, p_cost, view.a_cost)
    share = min(100, view.a_revenue / p_rev * 100) if p_rev else 0
    mark = rp.expected_to_date / p_rev * 100 if p_rev else 0
    tiles.append((f"Revenue So Far · {rp.basis}", h.money(view.a_revenue),
                  f"Expected by today {h.money(rp.expected_to_date)} ({h.pct(rp.pace_ratio)} of pace)"
                  f'<div class="meter"><i style="width:{share:.1f}%"></i><b style="left:{mark:.1f}%"></b></div>'))
    tiles.append(("End-Of-Quarter Forecast", h.money(rp.forecast - cp.forecast),
                  f"Revenue at the current pace {h.money(rp.forecast)} − cost {h.money(cp.forecast)} ({cp.basis})"))
else:
    gap = view.a_profit - p_profit
    tiles.append(("Actual Profit", h.money(view.a_profit) if view.cost_months else "—",
                  f"Revenue {h.money(view.a_revenue_cost_months)} − cost {h.money(view.a_cost)} · {view.costs_label}",
                  "" if view.cost_months else "muted"))
    tiles.append(("Actual Vs Projected", ("▲ " if gap >= 0 else "▼ ") + h.money(gap) if view.cost_months else "—",
                  f"Revenue {h.money(view.a_revenue - p_rev)} · cost {h.money(view.a_cost - p_cost)}",
                  ("up" if gap >= 0 else "down") if view.cost_months else "muted"))
h.tiles(tiles)


# ---------- 1: sources
def actual_of(src: str) -> tuple[float, int, float]:
    spend = next((c.a_cost for c in view.costs if c.source == src), 0.0)
    lines = [x for x in view.revenue if x.source == src]
    return spend, sum(x.a_deals for x in lines), sum(x.a_revenue for x in lines)


h.heading("Sources", "1", "Type the Spend, the Revenue or the Deals for a source; the other two are worked out from "
          "its backbone cost per deal and avg deal. No-cost sources and Follow Up: type revenue or deals.")
names = [r.source for r in rows]
table = []
for r in rows:
    a_spend, a_deals, a_rev = actual_of(r.source)
    u = r.unit
    table.append({
        "Source": r.source,
        "Spend": num(None if r.kind == FOLLOW_UP_KIND else (r.spend * scale if r.spend is not None else None)),
        "Revenue": num(r.revenue * scale if r.revenue is not None else None),
        "Deals": num(r.deals * scale if r.deals is not None else None),
        "Set By": SET_BY[r.driver.kind],
        "Not Placed": num(None if r.unallocated is None else round(r.unallocated * scale, 2) + 0.0),
        "Backbone Spend": u.cost * scale, "Backbone Deals": u.deals * scale, "Backbone Revenue": u.revenue * scale,
        "Cost / Deal": num(u.cpd), "Avg Deal": num(u.avg),
        "Actual Spend": a_spend, "Actual Deals": a_deals, "Actual Revenue": a_rev,
        "Type": KIND[r.kind], "Notes": " · ".join(r.notes), "Use Exit Rows": False, "Remove": False,
    })
if table:
    key = f"sources_{qid}_{ver}"
    cols = list(table[0])
    st.data_editor(
        pd.DataFrame(table, columns=cols), key=key, hide_index=True, width="stretch", disabled=not edit or [
            c for c in cols if c not in ("Remove", "Spend", "Revenue", "Deals", "Use Exit Rows")],
        column_config={
            "Remove": st.column_config.CheckboxColumn(width="small"),
            "Backbone Spend": MONEY, "Backbone Deals": COUNT, "Backbone Revenue": MONEY,
            "Cost / Deal": MONEY, "Avg Deal": MONEY,
            "Spend": st.column_config.NumberColumn("Spend ✎", format="dollar", help="Type a budget"),
            "Revenue": st.column_config.NumberColumn("Revenue ✎", format="dollar", help="Type the revenue to aim for"),
            "Deals": st.column_config.NumberColumn("Deals ✎", format="%.2f", help="Type the number of deals"),
            "Set By": st.column_config.TextColumn(help="The number you typed for this source"),
            "Use Exit Rows": st.column_config.CheckboxColumn(
                width="small", help="Let the exit rows below set this source's deals (and so its spend)"),
            "Not Placed": st.column_config.NumberColumn(format="%.2f", help="Deals not yet placed on exit rows"),
            "Actual Spend": MONEY, "Actual Deals": st.column_config.NumberColumn(format="%d"), "Actual Revenue": MONEY,
            "Notes": st.column_config.TextColumn(width="large"),
        },
        on_change=edit_sources, args=(qid, key, names))
else:
    st.caption("No sources yet. Use Add Source below.")

if edit:
    with st.container(horizontal=True):
        unplaced = [r.source for r in rows if r.unallocated and abs(r.unallocated) >= 0.05 and r.unit.exits]
        if st.button("Place Deals By Backbone Mix", icon=":material/call_split:", disabled=not unplaced,
                     help="Spread each source's not-yet-placed deals over its exit rows in its backbone mix. "
                          "You can still edit any exit row afterwards."):
            for src in unplaced:
                split_by_mix(proj, src, bb, settings)
            put(proj)
            st.rerun()
        with st.popover("Add Source", icon=":material/add:"):
            mkt = marketing_names(ds, settings) | set(settings.get("own_no_cost_sources", []))
            on = {c.source for c in proj.marketing}
            pick = st.selectbox("From The Sheet", ["—"] + sorted(mkt - on), key=f"add_src_{qid}")
            typed = st.text_input("Or Type A Name", key=f"add_src_typed_{qid}",
                                  help="Must match the Source in the sheet exactly to pick up actuals.")
            name = typed.strip() or (pick if pick != "—" else "")
            if st.button("Add", disabled=not name, key=f"add_src_btn_{qid}"):
                put(add_source(proj, name))
                st.rerun()

# ---------- 2: exits
h.heading("Deals By Exit Strategy", "2", "Place each source's deals on its exit strategies. Type deals, avg deal or "
          "revenue on a row (revenue ÷ avg deal = deals). Follow Up is projected as one group.")
actual_rev = {(x.block, x.source, x.exit): x for x in view.revenue if x.kind != UNPROJECTED}
exit_rows = []
for line in proj.revenue:
    u = bb.units.get(line.source)
    b_deals, b_avg = (u.exits.get(line.exit, (0.0, None)) if u else (0.0, None))
    x = actual_rev.get((line.block, line.source, line.exit))
    exit_rows.append({"Source": line.source, "Exit": line.exit,
                      "P.Deals": line.p_deals * scale, "P.Avg": line.p_avg, "P.Revenue": line.p_revenue * scale,
                      "Backbone Deals": b_deals * scale, "Backbone Avg": num(b_avg),
                      "Actual Deals": x.a_deals if x else 0, "Actual Revenue": x.a_revenue if x else 0.0,
                      "Block": BLOCK_LABELS[line.block], "Remove": False})
if exit_rows:
    key = f"exits_{qid}_{ver}"
    cols = list(exit_rows[0])
    st.data_editor(
        pd.DataFrame(exit_rows, columns=cols), key=key, hide_index=True, width="stretch",
        disabled=not edit or [c for c in cols if c not in ("Remove", "P.Deals", "P.Avg", "P.Revenue")],
        column_config={"Remove": st.column_config.CheckboxColumn(width="small"), "Backbone Deals": COUNT,
                       "Backbone Avg": MONEY,
                       "P.Deals": st.column_config.NumberColumn("P.Deals ✎", format="%.2f"),
                       "P.Avg": st.column_config.NumberColumn("P.Avg ✎", format="dollar"),
                       "P.Revenue": st.column_config.NumberColumn("P.Revenue ✎", format="dollar"),
                       "Actual Deals": st.column_config.NumberColumn(format="%d"), "Actual Revenue": MONEY},
        on_change=edit_exits, args=(qid, key))
loose = [x for x in view.revenue if x.kind == UNPROJECTED]
if loose:
    h.show(h.table(["Actual Deals Without An Exit Row", "Exit Strategy", "Deals", "Revenue"],
                   [[h.esc(x.label), h.esc(x.exit), str(x.a_deals), h.money(x.a_revenue)] for x in loose],
                   lambda n: "auto", left=(0, 1)))
fu_actual = {}
for x in view.revenue:
    if x.source == FOLLOW_UP:
        for s, (d, r) in x.contributors.items():
            fu_actual[s] = (fu_actual.get(s, (0, 0.0))[0] + d, fu_actual.get(s, (0, 0.0))[1] + r)
b_fu = b_r[~b_r["source"].isin(proj.projected_sources())]
b_fu = b_fu.groupby("source")["revenue"].agg(["size", "sum"])
fu_sources = sorted(set(fu_actual) | set(b_fu.index))
if fu_sources:
    with st.expander("Follow Up Sources (Backbone And Actual)", icon=":material/call_split:"):
        h.show(h.table(["Source", "Backbone Deals", "Backbone Revenue", "Actual Deals", "Actual Revenue"],
                       [[h.esc(s), h.num(b_fu.loc[s, "size"] / q * scale if s in b_fu.index else 0),
                         h.money(b_fu.loc[s, "sum"] / q * scale if s in b_fu.index else 0),
                         str(fu_actual.get(s, (0, 0))[0]), h.money(fu_actual.get(s, (0, 0.0))[1])]
                        for s in fu_sources]))
if edit:
    with st.popover("Add Exit Row", icon=":material/add:"):
        srcs = [c.source for c in proj.marketing] + [FOLLOW_UP]
        src = st.selectbox("Source", srcs, key=f"add_rev_src_{qid}")
        ex = st.selectbox("Exit Strategy", KNOWN_EXITS, key=f"add_rev_exit_{qid}")
        if st.button("Add", key=f"add_rev_btn_{qid}"):
            put(add_revenue_line(proj, block_of(ex), src, ex))
            st.rerun()

# ---------- 3: non-marketing
h.heading("Non-Marketing Costs", "3", "Payroll, consulting and general expenses: typed, starting at the backbone.")
nm_rows = []
for line in proj.non_marketing:
    b = float(b_c.loc[b_c["source"] == line.source, "cost"].sum()) / q
    nm_rows.append({"Line": line.source, "Group": "Payroll" if line.source in payroll else "Other",
                    "Backbone Cost": b * scale, "P.Cost": line.p_cost * scale,
                    "Actual Cost": next((c.a_cost for c in view.costs if c.source == line.source), 0.0)})
if nm_rows:
    key = f"nm_{qid}_{ver}"
    st.data_editor(pd.DataFrame(nm_rows), key=key, hide_index=True, width="stretch",
                   disabled=not edit or ["Line", "Group", "Backbone Cost", "Actual Cost"],
                   column_config={"Backbone Cost": MONEY, "P.Cost": st.column_config.NumberColumn("P.Cost ✎",
                                  format="dollar"), "Actual Cost": MONEY},
                   on_change=edit_costs, args=(qid, key))

# ---------- 4: totals
h.heading("Totals", "4", f"{shown.label} · actual costs cover {view.costs_label}")
base = {k: v * scale for k, v in backbone_tot.items()}
rev_by_block = {b: sum(r.p_revenue for r in proj.revenue if r.block == b) * scale for b in BLOCK_LABELS}
act_by_block = {b: sum(x.a_revenue for x in view.revenue if x.block == b) for b in BLOCK_LABELS}
b_by_block = {b: float(b_r.loc[b_r["exit"].map(block_of) == b, "revenue"].sum()) / q * scale for b in BLOCK_LABELS}
mkt_b = float(b_c.loc[b_c["source"].isin(marketing_names(ds, settings)), "cost"].sum()) / q * scale
excl = set(settings.get("pct_base_excluded_exits", []))
pct_base_p = (sum(r.p_revenue for r in proj.revenue if r.exit not in excl) + tot["not_placed"]) * scale
pct_base_b = float(b_r.loc[~b_r["exit"].isin(excl), "revenue"].sum()) / q * scale
lines = [(f"Revenue · {lbl}", b_by_block[b], rev_by_block[b], act_by_block[b], "") for b, lbl in BLOCK_LABELS.items()]
if abs(tot["not_placed"]) >= 0.5:
    lines.append(("Revenue · Not Yet On An Exit Row", 0.0, tot["not_placed"] * scale, 0.0, "auto"))
lines += [("Revenue", base["revenue"], p_rev, view.a_revenue, "sub"),
          ("Marketing Cost", mkt_b, tot["marketing"] * scale,
           sum(c.a_cost for c in view.costs if c.kind != "non_marketing"), ""),
          ("Non-Marketing Cost", base["cost"] - mkt_b, tot["non_marketing"] * scale,
           sum(c.a_cost for c in view.costs if c.kind == "non_marketing"), ""),
          ("Cost", base["cost"], p_cost, view.a_cost, "sub"),
          ("Profit", base["profit"], p_profit, view.a_profit, "tot")]
if in_progress:  # compare with what the projection expects by today, not the whole quarter
    rev_f = elapsed_days(shown, ds.today) / shown.days
    cost_f = len(view.cost_months) / len(shown.months)
    lines = [(lbl, b, p, a, k, p * (cost_f if "Cost" in lbl else rev_f)) for lbl, b, p, a, k in lines]
    lines[-1] = (*lines[-1][:5], p_profit * cost_f)  # profit is only measurable over cost-complete months
else:
    lines = [(*x, x[2]) for x in lines]
no_costs = not view.cost_months
body = [[lbl, h.money(b), h.money(p), "—" if lbl == "Profit" and no_costs else h.money(a),
         h.signed_cell(None if lbl == "Profit" and no_costs else (e - a if "Cost" in lbl else a - e))]
        for lbl, b, p, a, _, e in lines]
body.append(["Cost % (of revenue excl. " + ", ".join(sorted(excl)) + ")",
             h.pct(base["cost"] / pct_base_b if pct_base_b else None),
             h.pct(p_cost / pct_base_p if pct_base_p else None),
             h.pct(view.a_pct), ""])
classes = [x[4] for x in lines] + [""]
diff_label = "Vs Pace By Today" if in_progress else "Difference"
h.show(h.table(["", f"Backbone ({bb.label})", "Projected", "Actual", diff_label], body, lambda n: classes[n]))
rec = reconcile(ds, view)
h.status(("✓ Actuals add up to the sheet: " if rec.ok else "⚠ Actuals don't add up to the sheet: ")
         + f"costs {h.money(rec.sheet_cost, 2)}, revenue {h.money(rec.sheet_revenue, 2)} from {rec.sheet_deals} deals. "
         + ("Vs pace compares actuals with the share of the projection expected by today (revenue by days "
            "elapsed, costs by completed months). " if in_progress else "")
         + "Green = better: more revenue or profit, less cost.")

# ---------- work back from a profit target
if edit:
    with st.expander("Work Back From A Profit Target", icon=":material/flag:"):
        t_key = f"target_{qid}_{ver}"
        tc = st.columns([1.3, 3], vertical_alignment="bottom")
        tc[0].number_input(f"Target Profit For {period.label}", min_value=0.0, step=10000.0, format="%.0f",
                           value=proj.profit_target, key=t_key, on_change=set_field,
                           args=(qid, t_key, "profit_target"), placeholder="e.g. 400000")
        if proj.profit_target is None:
            tc[1].caption("Type the profit you want. Non-marketing costs, Follow Up, Fix & Flip and Buy & Hold stay as "
                          "projected above; the plans work out the marketing deals and spend needed.")
        elif not bb.months:
            tc[1].caption("No backbone before this quarter, so the plans can't be worked out.")
        else:
            fixed_costs, fixed_revenue = fixed_parts(proj)
            needed = needed_contribution(proj.profit_target, fixed_costs, fixed_revenue)
            tc[1].html(f'<p class="status">Fixed costs {h.money(fixed_costs)} · fixed revenue {h.money(fixed_revenue)} '
                       f"· marketing sources must bring <b>{h.money(needed)}</b> after their own spend.</p>")
            econ = source_economics(ds, proj, bb.months, settings)
            cap = settings.get("scale_cap", 1.5)
            plans = ((plan_a(needed, econ), f"Cheapest cost per deal first, up to {cap:g}× each source's best "
                      "quarter."),
                     (plan_b(needed, econ), "Your current main-revenue deals, all scaled by one factor."))
            for col, (plan, desc) in zip(st.columns(2), plans, strict=True):
                with col:
                    letter = plan.name.split(":")[0]
                    k_txt = f" · ×{plan.k:.2f}" if plan.k is not None else ""
                    st.html(f'<div style="font-family:var(--display);font-size:17px;font-weight:700;'
                            f'color:var(--heading)">Plan {h.esc(plan.name)}{k_txt}</div><p class="status">{desc}</p>')
                    prow = [[h.esc(x.source) + (" " + h.pill("over cap", "scale") if x.over_cap else ""),
                             h.num(x.deals, 1), h.money(x.budget), h.money(x.contribution)] for x in plan.lines]
                    prow.append(["Plan Total", "", h.money(plan.budget), h.money(plan.achieved)])
                    last = len(prow) - 1
                    h.show(h.table(["Source", "Deals", "Spend", "Brings In"], prow,
                                   lambda n, last=last: "tot" if n == last else ""))
                    if plan.shortfall > 0.5:
                        h.box(f"Short of target by {h.money(plan.shortfall)}: the usable sources hit their caps.",
                              "bad")
                    if plan.lines and st.button(f"Use Plan {letter}", key=f"use_{letter}_{qid}_{ver}",
                                                help="Sets those sources' deals (and so their spend) in table 1."):
                        use_plan(proj, plan, bb, settings)
                        put(proj)
                        st.rerun()

with st.expander("Saved Versions", icon=":material/history:"):
    revs = store.list_revisions(qid)
    if not revs:
        st.caption("Nothing saved for this quarter yet.")
    else:
        st.dataframe(pd.DataFrame([{"Version": r["id"], "Saved": f"{r['saved_at']:%b %-d, %Y %-I:%M %p}",
                                    "By": r["saved_by"], "Note": r["note"]} for r in revs]),
                     hide_index=True, width="stretch")
        vk = f"hist_{qid}"
        pick = st.segmented_control("Open A Version", [r["id"] for r in revs], default=revs[0]["id"],
                                    format_func=lambda i: f"#{i}", key=vk)
        if st.button("Open", key=f"hist_open_{qid}", help="Loads it as the working copy; save to make it current."):
            load(qid, store.get_revision(pick))
            state["dirty"][qid] = pick != revs[0]["id"]
            st.rerun()
