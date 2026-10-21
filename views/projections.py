"""Projections: build a quarter on its projection base (the quarter before, by default). Every source starts at the
base's actuals; type spend, revenue or deals per source and the rest is worked out in whole deals, which follow onto
the source's exit rows; non-marketing costs are typed. Edits are collected and applied together (Apply Changes).
Saved as revisions in the app database (never in the sheet)."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from streamlit_sortables import sort_items

from projection.data.schema import KNOWN_EXITS, block_of
from projection.metrics import roas as roas_m
from projection.metrics.core import in_months, marketing_names
from projection.metrics.deals import deal_list
from projection.metrics.follow_up import UNPROJECTED
from projection.metrics.pacing import cost_pace, daily_pace
from projection.metrics.quarter import QuarterView, quarter_view
from projection.model import FOLLOW_UP, QuarterProjection
from projection.periods import Month, Period, elapsed_days, period_of
from projection.plan import (
    FOLLOW_UP_KIND,
    NO_COST,
    add_active_sources,
    backbone,
    edit_exit,
    prefill,
    prefill_actuals,
    relink,
    reorder,
    reorder_exits,
    set_driver,
    set_manual,
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
from ui.brand import sortable_style
from ui.clicktable import clickable
from ui.layout import fit
from ui.state import get_dataset, get_settings, get_store

MONEY = st.column_config.NumberColumn(format="dollar")
COUNT = st.column_config.NumberColumn(format="%.2f")
ROAS = st.column_config.NumberColumn(format="%.2fx", help="Return on ad spend: revenue ÷ marketing spend")
NAN = float("nan")
SET_BY = {"spend": "Spend", "revenue": "Revenue", "deals": "Deals", "exits": "Exit Rows", "manual": "Manual"}
KIND = {"marketing": "Marketing", NO_COST: "No Spend", FOLLOW_UP_KIND: "Follow Up"}
BACKBONES = {"last_quarter": "Last Quarter", "last_2_quarters": "Last 2 Quarters", "all": "All Since Start",
             "custom": "Custom"}


def num(x: float | None) -> float:
    return NAN if x is None else x


def roas(revenue: float | None, spend: float | None) -> float:
    return revenue / spend if revenue is not None and spend else NAN


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


def has_numbers(p: QuarterProjection) -> bool:
    """Any cost, deals or typed number on it (a version saved as bare names has none)."""
    return (any(c.p_cost for c in p.marketing + p.non_marketing) or any(r.p_deals for r in p.revenue)
            or any(d.typed and d.value for d in p.drivers.values()))


def is_empty(p: QuarterProjection) -> bool:
    return not p.marketing and not p.revenue and not p.drivers


def pending(key: str) -> dict:
    return (st.session_state.get(key) or {}).get("edited_rows", {})


def apply_sources(p: QuarterProjection, bb, edits: dict, names: list[str], no_history: set[str]) -> None:
    """Sources table edits. A manual source (or one with no history) takes each typed number as is; any other source
    takes the one you typed (if several, Deals wins over Revenue over Spend) and the rest is worked out."""
    drop = set()
    for row, changes in edits.items():
        src = names[int(row)]
        if changes.get("Remove"):
            drop.add(src)
            continue
        d = p.drivers.get(src)
        typed = {k: changes[c] for c, k in (("Spend", "spend"), ("Revenue", "revenue"), ("Deals", "deals"))
                 if c in changes and changes[c] is not None}
        if src == FOLLOW_UP:
            typed.pop("spend", None)  # Follow Up has no spend: project it by revenue or deals
        manual = changes.get("Manual", d is not None and d.kind == "manual")
        if manual and src != FOLLOW_UP or (typed and src in no_history):
            set_manual(p, src, bb, settings, **typed)
        elif "Manual" in changes:  # unticked: the exit rows set its deals again
            set_driver(p, src, "exits", 0, bb, settings)
        for kind in ("spend", "revenue", "deals"):
            if kind in typed and not (manual or src in no_history):
                set_driver(p, src, kind, typed[kind], bb, settings)
    if drop:
        p.marketing = [c for c in p.marketing if c.source not in drop]
        p.revenue = [r for r in p.revenue if r.source not in drop]
        p.drivers = {k: v for k, v in p.drivers.items() if k not in drop}


def apply_exits(p: QuarterProjection, bb, edits: dict) -> None:
    drop = set()
    for row, changes in edits.items():
        if changes.get("Remove"):
            drop.add(int(row))
            continue
        num_or_none = {k: (float(changes[c] or 0) if c in changes else None)
                       for c, k in (("P.Deals", "deals"), ("P.Avg", "avg"), ("P.Revenue", "revenue"))}
        edit_exit(p, int(row), bb, settings, **num_or_none)
    if drop:
        p.revenue = [r for i, r in enumerate(p.revenue) if i not in drop]
        sync_costs(p, bb, settings)


def apply_costs(p: QuarterProjection, edits: dict) -> None:
    for row, changes in edits.items():
        if "P.Cost" in changes:
            p.non_marketing[int(row)].p_cost = float(changes["P.Cost"] or 0)


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
c[0].segmented_control("Projection Base (Actuals The Projection Is Built On)", list(BACKBONES), default=proj.lookback,
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
    st.select_slider("Projection Base Months", options=before, value=(lo, hi), format_func=lambda m: m.label, key=rk,
                     on_change=lambda: (set_field(qid, rk, "lookback_from", lambda v: v[0].key),
                                        set_field(qid, rk, "lookback_to", lambda v: v[1].key)))
    if not (proj.lookback_from and proj.lookback_to):
        proj.lookback_from, proj.lookback_to = lo.key, hi.key
        put(proj)
        st.rerun()

bb = backbone(ds, proj, period)
finished = period.end < ds.today
if (finished or bb.months) and (is_empty(proj) and store.latest_revision(qid) is None or not has_numbers(proj)):
    # a new quarter (or one saved with no numbers in it) starts as the projection base repeated; a finished quarter
    # starts as a copy of its own actuals, to edit back to what was projected
    fresh = prefill_actuals(ds, period, settings, proj) if finished else prefill(ds, period, settings, proj)
    if has_numbers(fresh):
        put(fresh)
        st.toast("Filled with this quarter's actuals: change what was projected, then Save" if finished
                 else "Pre-filled from the projection base: Save to keep it", icon=":material/auto_fix:")
        st.rerun()
fixed = relink(proj, bb, settings) if state.setdefault("relinked", {}).get(qid) != ver else []
state["relinked"][qid] = ver  # at most once per change, so it can never loop
if fixed:  # a version saved before deals were whole and linked to their exit rows
    put(proj)
    st.toast("Exit rows put back in step with their sources (" + ", ".join(fixed) + "). Save to keep it.",
             icon=":material/auto_fix:")
    st.rerun()

rev_id = state["rev"].get(qid)
saved = store.get_revision(rev_id) if rev_id else None
saved_txt = (f"Saved version #{rev_id}, {saved['saved_at']:%b %-d, %-I:%M %p}"
             + (f" by {h.esc(saved['saved_by'])}" if saved["saved_by"] else "")) if saved else "Not saved yet"
dirty = " · <b>Unsaved changes</b>" if state["dirty"].get(qid) else ""
when = ("Complete: actuals are final." if period.end < ds.today else
        f"In progress: revenue to {ds.today:%b %-d}, costs post at month end." if period.start <= ds.today else
        "Future quarter.")
h.status(f"{when} · Projection base: <b>{bb.label}</b> actuals{' per quarter' if bb.quarters > 1 else ''} · "
         f"{saved_txt}{dirty}")
if finished and not saved:
    h.box(f"{period.label} is finished, so it starts as a copy of its own actuals (projected = actual). Change any "
          "number back to what was projected, then <b>Save</b>.", "info")
elif not bb.months:
    h.box("No complete months before this quarter, so there's no projection base: type every number yourself.", "warn")
elif not saved:
    h.box(f"Pre-filled with the {bb.label} actuals. Change what you plan to do differently, then <b>Save</b> "
          "(save at the start of the quarter; every version is kept).", "info")

# ---------- a saved quarter that doesn't match the active source list
active = list(dict.fromkeys(settings.get("active_sources", [])))
on = [c.source for c in proj.marketing]
missing, extra = [a for a in active if a not in on], [s for s in on if s not in active]
if show == "quarter" and active and (missing or extra) and not is_empty(proj) and not finished:
    parts = []
    if missing:
        parts.append("<b>Active sources missing here:</b> " + ", ".join(h.esc(s) for s in missing))
    if extra:
        parts.append("<b>On this projection but not on the active list:</b> " + ", ".join(h.esc(s) for s in extra))
    h.box("This quarter doesn't match your active source list (Settings). " + " · ".join(parts) + ". "
          "<b>Rebuild From Projection Base</b> starts over from the base with exactly the active sources; "
          "<b>Add Missing Active Sources</b> keeps what you typed and adds the missing ones (remove others with the "
          "Remove box).",
          "warn")
    with st.container(horizontal=True):
        if st.button("Rebuild From Projection Base", type="primary", icon=":material/restart_alt:",
                     disabled=not bb.months, key=f"rebuild_{qid}_{ver}"):
            put(prefill(ds, period, settings, proj))
            st.rerun()
        if missing and st.button("Add Missing Active Sources", icon=":material/playlist_add:",
                                 key=f"addact_{qid}_{ver}"):
            add_active_sources(proj, ds, period, settings)
            put(proj)
            st.rerun()

# ---------- actions
a = st.columns([1.1, 1.1, 1.8, 3.4], vertical_alignment="bottom")
note = a[3].text_input("Note", placeholder="What changed (optional)", label_visibility="collapsed")
unapplied = sum(len(pending(f"{k}_{qid}_{ver}")) for k in ("sources", "exits", "nm"))
if a[0].button("Save", type="primary", icon=":material/save:", width="stretch",
               disabled=not state["dirty"].get(qid) or bool(unapplied),
               help="Apply or cancel your table edits first" if unapplied else None):
    new_id = store.save_revision(qid, proj.model_dump(), by=user(), note=note)
    load(qid, store.get_revision(new_id))
    st.toast(f"Saved version #{new_id}", icon=":material/check:")
    st.rerun()
if a[1].button("Discard", icon=":material/undo:", disabled=not state["dirty"].get(qid), width="stretch"):
    load(qid)
    st.rerun()
if finished:
    if a[2].button("Reset To Actuals", icon=":material/restart_alt:", width="stretch",
                   help=f"Start again from {period.label}'s own actuals (your typed numbers are cleared until you "
                        "save)."):
        put(prefill_actuals(ds, period, settings, proj))
        st.rerun()
elif a[2].button("Reset To Projection Base", icon=":material/restart_alt:", width="stretch", disabled=not bb.months,
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
mkt_names = marketing_names(ds, settings)
backbone_tot["marketing"] = float(b_c.loc[b_c["source"].isin(mkt_names), "cost"].sum()) / q
a_mkt = sum(c.a_cost for c in view.costs if c.kind != "non_marketing")

# ---------- summary
in_progress = shown.start <= ds.today <= shown.end
p_rev, p_cost, p_profit = tot["revenue"] * scale, tot["cost"] * scale, tot["profit"] * scale
tiles = [("Projected Profit", h.money(p_profit), f"Revenue {h.money(p_rev)} − cost {h.money(p_cost)}<br>Margin "
          f"{h.pct(p_profit / p_rev if p_rev else None)} · {h.num(tot['deals'] * scale)} deals"),
         (f"Projection Base · {bb.label}", h.money(backbone_tot["profit"] * scale),
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
p_roas, b_roas = roas(tot["revenue"], tot["marketing"]), roas(backbone_tot["revenue"], backbone_tot["marketing"])
a_roas = roas(view.a_revenue_cost_months, a_mkt) if view.cost_months else NAN
fmt_x = lambda x: "—" if x != x else f"{x:.2f}x"  # noqa: E731
tiles.insert(1, ("ROAS · Projected", fmt_x(p_roas),
                 f"Revenue ÷ marketing spend<br>Base {fmt_x(b_roas)} · actual {fmt_x(a_roas)}"
                 + ("" if view.cost_months else " (no cost month yet)")))
h.tiles(tiles)


@st.dialog("ROAS Breakdown", width="large")
def roas_breakdown() -> None:
    """Overall, per source and per exit ROAS, projected next to actual."""
    pr = roas_m.projected(proj, rows)
    ac = roas_m.actual(ds, proj, view.cost_months, settings) if view.cost_months else None
    x = lambda v: "—" if v is None else f"{v:.2f}x"  # noqa: E731
    m = lambda v: "—" if v is None else h.money(v)  # noqa: E731
    act_note = (f"Actual = {view.costs_label} (revenue from the same months, so it lines up with spend)."
                if ac else "No cost month has posted yet in this period, so there is no actual ROAS.")
    h.status(f"ROAS = revenue ÷ marketing spend. Projected = {shown.label}. {act_note} Per exit, a source's spend "
             "is shared by deals (deals × its cost per deal). No-spend sources show —.")
    a_tot = (ac.spend, ac.revenue, ac.roas) if ac else (None, None, None)
    h.show(h.table(["Overall", "Spend", "Revenue", "ROAS"], [
        ["Projected", m(pr.spend * scale), m(pr.revenue * scale), f"<b>{x(pr.roas)}</b>"],
        ["Actual", m(a_tot[0]), m(a_tot[1]), f"<b>{x(a_tot[2])}</b>"],
        [f"Projection Base ({bb.label})", m(backbone_tot["marketing"] * scale), m(backbone_tot["revenue"] * scale),
         x(b_roas if b_roas == b_roas else None)]]))

    def joined(p_lines, a_lines, key):
        a_by = {key(r): r for r in a_lines}
        keys = [key(r) for r in p_lines] + [k for k in (key(r) for r in a_lines) if k not in {key(r) for r in p_lines}]
        p_by = {key(r): r for r in p_lines}
        out = []
        for k in keys:
            pl, al = p_by.get(k), a_by.get(k)
            out.append([*(h.esc(v) for v in k),
                        m(pl.spend * scale if pl and pl.spend else None), m(pl.revenue * scale if pl else None),
                        x(pl.roas if pl else None),
                        m(al.spend if al else None), m(al.revenue if al else None), x(al.roas if al else None)])
        return out

    cols = ["P. Spend", "P. Revenue", "P. ROAS", "A. Spend", "A. Revenue", "A. ROAS"]
    st.html('<div class="sh"><span class="t1">By Source</span></div>')
    h.show(h.table(["Source", *cols], joined(pr.sources, ac.sources if ac else [], lambda r: (r.source,))))
    st.html('<div class="sh"><span class="t1">By Exit Strategy</span></div>')
    h.show(h.table(["Source", "Exit", *cols], joined(pr.exits, ac.exits if ac else [], lambda r: (r.source, r.exit)),
                   left=(0, 1)))


if st.button("View ROAS Breakdown", icon=":material/insights:", type="tertiary", key=f"roas_{qid}",
             help="Overall, per source and per exit ROAS, projected and actual"):
    roas_breakdown()


@st.dialog("Deals", width="large")
def deals_dialog(exit_: str | None = None, source: str | None = None) -> None:
    """The deals behind a revenue number: actual (this period to date) or the projection base's."""
    exits = ["All"] + list(dict.fromkeys(KNOWN_EXITS + sorted(set(ds.revenues["exit"]) - {""})))
    srcs = ["All"] + [c.source for c in proj.marketing] + [FOLLOW_UP]
    f = st.columns([1.2, 1.4, 1.4], vertical_alignment="bottom")
    k = f"{exit_}|{source}|{st.session_state.get('deals_opened', 0)}"  # fresh filters each time it opens
    when = f[0].segmented_control("Deals From", ["actual", "base"], default="actual", key=f"deals_when_{k}",
                                  format_func=lambda w: "Actual" if w == "actual" else "Projection Base") or "actual"
    ex = f[1].selectbox("Exit Strategy", exits, index=exits.index(exit_) if exit_ in exits else 0,
                        key=f"deals_exit_{k}")
    sc = f[2].selectbox("Source", srcs, index=srcs.index(source) if source in srcs else 0, key=f"deals_src_{k}",
                        help="Follow Up = every source not on this projection.")
    months = [m for m in shown.months if m <= Month.of(ds.today)] if when == "actual" else bb.months
    df = deal_list(ds, months, proj, None if ex == "All" else ex, None if sc == "All" else sc)
    h.status((f"Actual · {shown.label} to date · " if when == "actual" else f"Projection Base · {bb.label} · ")
             + f"<b>{len(df)} deal{'' if len(df) == 1 else 's'}</b> · revenue {h.money(df['Revenue'].sum())}"
             + (f" · avg {h.money(df['Revenue'].mean())}" if len(df) else "")
             )
    if len(df):
        st.dataframe(df, hide_index=True, width="stretch", height=fit(len(df)),
                     column_config={"Revenue": MONEY, "Date Closed": st.column_config.DateColumn(format="MMM D, YYYY")})
    else:
        st.caption("No deals for this choice.")


# ---------- 1: sources
def actual_of(src: str) -> tuple[float, int, float]:
    spend = next((c.a_cost for c in view.costs if c.source == src), 0.0)
    lines = [x for x in view.revenue if x.source == src]
    return spend, sum(x.a_deals for x in lines), sum(x.a_revenue for x in lines)


DEALS_FMT = "%d" if edit else "%.1f"
h.heading("Sources", "1", "Type the Spend, the Revenue or the Deals for a source; the other two are worked out from "
          "its projection base cost per deal and avg deal, in whole deals, and its exit rows (table 2) follow in their "
          "current mix. New sources with no history: tick Manual and type all three. Edits apply when you click "
          "<b>Apply Changes</b>.")
names = [r.source for r in rows]
no_history = {r.source for r in rows if r.kind != FOLLOW_UP_KIND and r.unit.avg is None}
any_unplaced = any(r.unallocated is not None and abs(r.unallocated) >= 0.5 for r in rows)
table = []
for r in rows:
    a_spend, a_deals, a_rev = actual_of(r.source)
    u = r.unit
    spend = None if r.kind == FOLLOW_UP_KIND else (r.spend * scale if r.spend is not None else None)
    rec_ = {
        "Source": r.source, "Manual": r.driver.kind == "manual",
        "Spend": num(spend),
        "Revenue": num(r.revenue * scale if r.revenue is not None else None),
        "Deals": num(r.deals * scale if r.deals is not None else None),
        "ROAS": roas(r.revenue, r.spend if r.kind != FOLLOW_UP_KIND else None),
        "Set By": SET_BY[r.driver.kind] if r.driver.typed or r.driver.kind == "exits" else "Projection Base",
    }
    if any_unplaced:
        rec_["No Exit Row"] = num(None if r.unallocated is None else round(r.unallocated * scale) + 0.0)
    rec_ |= {
        "Base Spend": u.cost * scale, "Base Deals": u.deals * scale, "Base Revenue": u.revenue * scale,
        "Base ROAS": roas(u.revenue, u.cost), "Cost / Deal": num(u.cpd), "Avg Deal": num(u.avg),
        "Actual Spend": a_spend, "Actual Deals": a_deals, "Actual Revenue": a_rev,
        "Actual ROAS": roas(a_rev, a_spend), "Type": KIND[r.kind], "Notes": " · ".join(r.notes), "Remove": False,
    }
    table.append(rec_)
src_key = f"sources_{qid}_{ver}"
if table:
    cols = list(table[0])
    st.data_editor(
        pd.DataFrame(table, columns=cols), key=src_key, hide_index=True, width="stretch", height=fit(len(table)),
        disabled=not edit or [c for c in cols if c not in ("Remove", "Spend", "Revenue", "Deals", "Manual")],
        column_config={
            "Remove": st.column_config.CheckboxColumn(width="small"),
            "Manual": st.column_config.CheckboxColumn(
                width=70, help="Type Spend, Deals and Revenue each on their own (for sources with no history)"),
            "Base Spend": MONEY, "Base Deals": COUNT, "Base Revenue": MONEY, "Base ROAS": ROAS,
            "Cost / Deal": MONEY, "Avg Deal": MONEY, "ROAS": ROAS, "Actual ROAS": ROAS,
            "Spend": st.column_config.NumberColumn("Spend ✎", format="dollar", help="Type a budget"),
            "Revenue": st.column_config.NumberColumn("Revenue ✎", format="dollar", help="Type the revenue to aim for"),
            "Deals": st.column_config.NumberColumn("Deals ✎", format=DEALS_FMT, help="Type the number of deals"),
            "Set By": st.column_config.TextColumn(
                help="The number you typed for this source; Projection Base = not typed yet"),
            "No Exit Row": st.column_config.NumberColumn(
                format="%d", help="Deals with no exit row to go on (add one in table 2); they count at the avg deal"),
            "Actual Spend": MONEY, "Actual Deals": st.column_config.NumberColumn(format="%d"), "Actual Revenue": MONEY,
            "Notes": st.column_config.TextColumn(width="large"),
        })
else:
    st.caption("No sources yet. Use Add Source below.")

if edit:
    with st.container(horizontal=True):
        with st.popover("Reorder Sources", icon=":material/drag_indicator:"):
            st.caption("Drag a source up or down; the exit rows below follow. Follow Up stays last.")
            current = [c.source for c in proj.marketing]
            moved = sort_items(current, direction="vertical", custom_style=sortable_style(), key=f"order_{qid}_{ver}")
            if moved != current:
                reorder(proj, moved)
                put(proj)
                st.rerun()
            default = [s for s in dict.fromkeys(settings.get("active_sources", [])) if s in current]
            if st.button("Default Order", icon=":material/sort:", disabled=current[:len(default)] == default,
                         key=f"order_default_{qid}", help="The order of the active sources in Settings"):
                reorder(proj, default)
                put(proj)
                st.rerun()
        with st.popover("Add Source", icon=":material/add:"):
            mkt = (marketing_names(ds, settings) | set(ds.revenues["source"]) | set(ds.leads["source"])) - {""}
            on = {c.source for c in proj.marketing}
            pick = st.selectbox("From The Sheet", ["—"] + sorted(mkt - on), key=f"add_src_{qid}")
            typed = st.text_input("Or Type A Name", key=f"add_src_typed_{qid}",
                                  help="Must match the Source in the sheet exactly to pick up actuals.")
            name = typed.strip() or (pick if pick != "—" else "")
            if st.button("Add", disabled=not name, key=f"add_src_btn_{qid}"):
                put(add_source(proj, name))
                st.rerun()

# ---------- 2: exits
h.heading("Deals By Exit Strategy", "2", "Each source's deals on its exit strategies, in whole deals. They follow the "
          "source's number in its current mix; type deals, avg deal or revenue on a row (revenue ÷ avg deal = deals) "
          "and the source follows the rows. Follow Up is projected as one group.")
actual_rev = {(x.block, x.source, x.exit): x for x in view.revenue if x.kind != UNPROJECTED}
cpd_of = {r.source: r.unit.cpd for r in rows}
exit_rows = []
for line in proj.revenue:
    u = bb.units.get(line.source)
    b_deals, b_avg = (u.exits.get(line.exit, (0.0, None)) if u else (0.0, None))
    x = actual_rev.get((line.block, line.source, line.exit))
    d = proj.drivers.get(line.source)
    manual_spend = d.spend / d.deals if d is not None and d.kind == "manual" and d.deals else None
    cpd = manual_spend if manual_spend is not None else cpd_of.get(line.source)
    exit_rows.append({"Source": line.source, "Exit": line.exit,
                      "P.Deals": line.p_deals * scale, "P.Avg": line.p_avg, "P.Revenue": line.p_revenue * scale,
                      "ROAS": roas(line.p_revenue, line.p_deals * cpd if cpd else None),
                      "Base Deals": b_deals * scale, "Base Avg": num(b_avg),
                      "Actual Deals": x.a_deals if x else 0, "Actual Revenue": x.a_revenue if x else 0.0,
                      "Block": BLOCK_LABELS[line.block], "Remove": False})
exit_key = f"exits_{qid}_{ver}"
if exit_rows:
    cols = list(exit_rows[0])
    st.data_editor(
        pd.DataFrame(exit_rows, columns=cols), key=exit_key, hide_index=True, width="stretch",
        height=fit(len(exit_rows)),
        disabled=not edit or [c for c in cols if c not in ("Remove", "P.Deals", "P.Avg", "P.Revenue")],
        column_config={"Remove": st.column_config.CheckboxColumn(width="small"), "Base Deals": COUNT,
                       "Base Avg": MONEY, "ROAS": st.column_config.NumberColumn(
                           format="%.2fx", help="Exit revenue ÷ its share of the source's spend (deals × cost/deal)"),
                       "P.Deals": st.column_config.NumberColumn("P.Deals ✎", format=DEALS_FMT),
                       "P.Avg": st.column_config.NumberColumn("P.Avg ✎", format="dollar"),
                       "P.Revenue": st.column_config.NumberColumn("P.Revenue ✎", format="dollar"),
                       "Actual Deals": st.column_config.NumberColumn(format="%d"), "Actual Revenue": MONEY})
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
    with st.expander("Follow Up Sources (Projection Base And Actual)", icon=":material/call_split:"):
        h.show(h.table(["Source", "Base Deals", "Base Revenue", "Actual Deals", "Actual Revenue"],
                       [[h.esc(s), h.num(b_fu.loc[s, "size"] / q * scale if s in b_fu.index else 0),
                         h.money(b_fu.loc[s, "sum"] / q * scale if s in b_fu.index else 0),
                         str(fu_actual.get(s, (0, 0))[0]), h.money(fu_actual.get(s, (0, 0.0))[1])]
                        for s in fu_sources]))
if edit:
    with st.container(horizontal=True):
        with st.popover("Reorder Exit Rows", icon=":material/drag_indicator:"):
            st.caption("Drag an exit row up or down; rows stay under their own source.")
            labels = [f"{i + 1}. {r.source} · {r.exit}" for i, r in enumerate(proj.revenue)]
            moved = sort_items(labels, direction="vertical", custom_style=sortable_style(), key=f"xorder_{qid}_{ver}")
            if moved != labels:
                reorder_exits(proj, [labels.index(x) for x in moved])
                put(proj)
                st.rerun()
        with st.popover("Add Exit Row", icon=":material/add:"):
            srcs = [c.source for c in proj.marketing] + [FOLLOW_UP]
            src = st.selectbox("Source", srcs, key=f"add_rev_src_{qid}")
            ex = st.selectbox("Exit Strategy", KNOWN_EXITS, key=f"add_rev_exit_{qid}")
            if st.button("Add", key=f"add_rev_btn_{qid}"):
                put(add_revenue_line(proj, block_of(ex), src, ex))
                st.rerun()
        mixable = [r.source for r in rows if r.unit.exits and r.deals]
        if st.button("Reset Exit Mix To Projection Base", icon=":material/call_split:", disabled=not mixable,
                     help="Re-place every source's deals over its exit rows in the projection base's mix."):
            for src in mixable:
                split_by_mix(proj, src, bb, settings)
            put(proj)
            st.rerun()

if st.button("View Deals", icon=":material/list_alt:", key=f"deals_exits_{qid}",
             help="Every actual or projection-base deal behind these rows: date, address, source, reps, revenue"):
    st.session_state["deals_opened"] = st.session_state.get("deals_opened", 0) + 1
    deals_dialog()

# ---------- 3: non-marketing
h.heading("Non-Marketing Costs", "3", "Payroll, consulting and general expenses: typed, starting at the projection "
          "base.")
nm_rows = []
for line in proj.non_marketing:
    b = float(b_c.loc[b_c["source"] == line.source, "cost"].sum()) / q
    nm_rows.append({"Line": line.source, "Group": "Payroll" if line.source in payroll else "Other",
                    "Base Cost": b * scale, "P.Cost": line.p_cost * scale,
                    "Actual Cost": next((c.a_cost for c in view.costs if c.source == line.source), 0.0)})
nm_key = f"nm_{qid}_{ver}"
if nm_rows:
    st.data_editor(pd.DataFrame(nm_rows), key=nm_key, hide_index=True, width="stretch", height=fit(len(nm_rows)),
                   disabled=not edit or ["Line", "Group", "Base Cost", "Actual Cost"],
                   column_config={"Base Cost": MONEY, "P.Cost": st.column_config.NumberColumn("P.Cost ✎",
                                  format="dollar"), "Actual Cost": MONEY})
    if edit:
        with st.popover("Reorder Lines", icon=":material/drag_indicator:"):
            labels = [c.source for c in proj.non_marketing]
            moved = sort_items(labels, direction="vertical", custom_style=sortable_style(), key=f"nmorder_{qid}_{ver}")
            if moved != labels:
                proj.non_marketing.sort(key=lambda c: moved.index(c.source))
                put(proj)
                st.rerun()

# ---------- pending edits: applied together
edits = {k: pending(k) for k in (src_key, exit_key, nm_key)}
n_edits = sum(len(e) for e in edits.values())
if edit and n_edits:
    with st.container(key="applybar", horizontal=True, vertical_alignment="center"):
        st.html(f'<span class="applybar-text"><b>{n_edits} row{"s" if n_edits > 1 else ""} edited</b> · '
                "not applied yet</span>")
        if st.button("Apply Changes", type="primary", icon=":material/check:", key=f"apply_{qid}_{ver}"):
            apply_sources(proj, bb, edits[src_key], names, no_history)
            apply_exits(proj, bb, edits[exit_key])
            apply_costs(proj, edits[nm_key])
            sync_costs(proj, backbone(ds, proj, period), settings)
            put(proj)
            st.rerun()
        if st.button("Cancel Edits", icon=":material/close:", key=f"cancel_{qid}_{ver}"):
            state["ver"][qid] = ver + 1
            st.rerun()

# ---------- 4: totals
h.heading("Totals", "4", f"{shown.label} · actual costs cover {view.costs_label}")
base = {k: v * scale for k, v in backbone_tot.items()}
exits_all = list(dict.fromkeys(KNOWN_EXITS + [r.exit for r in proj.revenue]
                                + [x.exit for x in view.revenue] + list(b_r["exit"].unique())))
exits_all = [e for e in exits_all if e]
p_by_exit = {e: sum(r.p_revenue for r in proj.revenue if r.exit == e) * scale for e in exits_all}
a_by_exit = {e: sum(x.a_revenue for x in view.revenue if x.exit == e) for e in exits_all}
b_by_exit = {e: float(b_r.loc[b_r["exit"] == e, "revenue"].sum()) / q * scale for e in exits_all}
mkt_b = backbone_tot["marketing"] * scale
excl = set(settings.get("pct_base_excluded_exits", []))
pct_base_p = (sum(r.p_revenue for r in proj.revenue if r.exit not in excl) + tot["not_placed"]) * scale
pct_base_b = float(b_r.loc[~b_r["exit"].isin(excl), "revenue"].sum()) / q * scale
lines = [(f"Revenue · {e}", b_by_exit[e], p_by_exit[e], a_by_exit[e], "")
         for e in exits_all if b_by_exit[e] or p_by_exit[e] or a_by_exit[e] or e in KNOWN_EXITS]
if abs(tot["not_placed"]) >= 0.5:
    lines.append(("Revenue · No Exit Row Yet", 0.0, tot["not_placed"] * scale, 0.0, "auto"))
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
body.append(["ROAS (Revenue ÷ Marketing Cost)", fmt_x(b_roas), fmt_x(p_roas), fmt_x(a_roas), ""])
body.append(["Cost % (of revenue excl. " + ", ".join(sorted(excl)) + ")",
             h.pct(base["cost"] / pct_base_b if pct_base_b else None),
             h.pct(p_cost / pct_base_p if pct_base_p else None),
             h.pct(view.a_pct), ""])
classes = [x[4] for x in lines] + ["", ""]
diff_label = "Vs Pace By Today" if in_progress else "Difference"
exit_of_row = {n: lbl.split(" · ", 1)[1] for n, (lbl, *_) in enumerate(lines)
               if lbl.startswith("Revenue · ") and lbl.split(" · ", 1)[1] in exits_all}
picked = clickable(h.table(["", f"Projection Base ({bb.label})", "Projected", "Actual", diff_label], body,
                           lambda n: classes[n], click=exit_of_row.get),
                   key=f"totals_{qid}", hint="Click to see the deals behind this revenue")
rec = reconcile(ds, view)
h.status(("✓ Actuals add up to the sheet: " if rec.ok else "⚠ Actuals don't add up to the sheet: ")
         + f"costs {h.money(rec.sheet_cost, 2)}, revenue {h.money(rec.sheet_revenue, 2)} from {rec.sheet_deals} "
         + f"deal{'' if rec.sheet_deals == 1 else 's'}. "
         + ("Vs pace compares actuals with the share of the projection expected by today (revenue by days "
            "elapsed, costs by completed months). " if in_progress else "")
         + "Green = better: more revenue or profit, less cost.")
st.caption("Click a revenue line (e.g. Revenue · Wholesale) to see the deals behind it.")
if picked:
    st.session_state["deals_opened"] = st.session_state.get("deals_opened", 0) + 1
    deals_dialog(picked)

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
            tc[1].caption("No projection base before this quarter, so the plans can't be worked out.")
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
                     hide_index=True, width="stretch", height=fit(len(revs)))
        vk = f"hist_{qid}"
        pick = st.segmented_control("Open A Version", [r["id"] for r in revs], default=revs[0]["id"],
                                    format_func=lambda i: f"#{i}", key=vk)
        if st.button("Open", key=f"hist_open_{qid}", help="Loads it as the working copy; save to make it current."):
            load(qid, store.get_revision(pick))
            state["dirty"][qid] = pick != revs[0]["id"]
            st.rerun()
