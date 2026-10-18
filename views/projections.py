"""Projections: one quarter's costs and revenue, projected vs actual, with suggestions; saved as revisions in the app
database (never in the sheet). Layout follows the approved mockup: C profit summary, A costs, B revenue, D3 target."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from projection.data.schema import KNOWN_EXITS, block_of
from projection.metrics.core import cost_complete_months, marketing_names
from projection.metrics.follow_up import UNPROJECTED
from projection.metrics.pacing import cost_pace, daily_pace
from projection.metrics.quarter import OTHER_MARKETING, QuarterView, quarter_view
from projection.model import BLOCKS, FOLLOW_UP, QuarterProjection
from projection.periods import Month, Period, period_of
from projection.planning import (
    BLOCK_LABELS,
    add_actual_lines,
    add_revenue_line,
    add_source,
    apply_plan,
    copy_lines,
    follow_up_sources,
    lines_from_history,
    monthly_costs,
    monthly_revenue,
    new_projection,
    previous_quarter,
    quarter_options,
    reconcile,
    scale_projection,
    unprojected_spend,
)
from projection.suggest.lookback import LOOKBACKS
from projection.suggest.marketing import reverse
from projection.suggest.profit_target import fixed_parts, needed_contribution, plan_a, plan_b, source_economics
from projection.suggest.quarter import (
    accept_budget,
    accept_revenue,
    budget_drift,
    fill_suggestions,
    mark_typed,
    quarter_suggestions,
)
from ui import html as h
from ui.state import get_dataset, get_settings, get_store

MONEY = st.column_config.NumberColumn(format="dollar")
COUNT = st.column_config.NumberColumn(format="%.2f")
ORIGIN = {"manual": "", "accepted_suggestion": "✓ Suggested", "override": "🟠 Override"}
NAN = float("nan")


def num(x: float | None) -> float:
    return NAN if x is None else x


def md_money(x: float, decimals: int = 2) -> str:
    """Dollar amount for markdown text (a bare $ starts math formatting)."""
    return h.money(x, decimals).replace("$", "\\$")


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


def fill(qid: str, group: str) -> None:
    p = draft(qid)
    fill_suggestions(p, quarter_suggestions(ds, p, by_key[qid], settings), group)
    put(p)


def start_from_suggestions(qid: str) -> None:
    """Lines from the suggestion window, then revenue suggestions, then budgets (which follow the deals)."""
    p = draft(qid)
    period = by_key[qid]
    p = lines_from_history(p, ds, quarter_suggestions(ds, p, period, settings).months, settings)
    fill_suggestions(p, quarter_suggestions(ds, p, period, settings), "revenue")
    fill_suggestions(p, quarter_suggestions(ds, p, period, settings), "marketing")
    put(p)


def set_field(qid: str, key: str, field: str) -> None:
    p = draft(qid)
    setattr(p, field, st.session_state[key])
    put(p)


def user() -> str:
    try:
        return st.user.email or ""
    except Exception:
        return ""


def flag_text(s, drift: float | None = None) -> str:
    if s is None:
        return ""
    notes = []
    f = getattr(s, "flags", None)
    if f is not None:
        notes += [n for n, on in (("⛔ Insufficient Data", f.insufficient), ("⚠️ Low Confidence", f.low_confidence),
                                  ("📈 Over Scale Cap", f.scale)) if on]
    if drift is not None:
        notes.append(f"🔄 Now ${drift:,.0f}")
    return " · ".join(notes)


def quarter_label(k: str) -> str:
    tag = " · Live" if k == current else (" · Done" if by_key[k].end < ds.today else " · Next")
    return by_key[k].label + tag


def subhead(text: str) -> None:
    st.html(f'<div class="side-h" style="font-size:14px;color:var(--heading)">{h.esc(text)}</div>')


# ---------- header and controls
st.title("Projections")
bar = st.columns([2.2, 3.2, 3.4], vertical_alignment="bottom")
keys = list(by_key)
qid = bar[0].selectbox("Quarter", keys, index=keys.index(current) if current in keys else len(keys) - 1,
                       format_func=quarter_label)
period = by_key[qid]
proj = draft(qid)
ver = state["ver"][qid]
show_opts = ["quarter"] + [m.key for m in period.months]
show = bar[1].segmented_control("Show", show_opts, default="quarter", key=f"show_{qid}",
                                format_func=lambda k: "Whole Quarter" if k == "quarter"
                                else Month.from_key(k).label[:3])
show = show or "quarter"
lb_key = f"lookback_{qid}_{ver}"
bar[2].selectbox("Suggestions Based On", list(LOOKBACKS), index=list(LOOKBACKS).index(proj.lookback),
                 format_func=LOOKBACKS.get, key=lb_key, on_change=set_field, args=(qid, lb_key, "lookback"))
if proj.lookback == "custom":
    before = [m.key for m in cost_complete_months(ds) if m.last_day < period.start]
    if before:
        cc = st.columns([2.2, 3.2, 1.7, 1.7])
        for col, field, label, default in ((cc[2], "lookback_from", "From", before[0]),
                                           (cc[3], "lookback_to", "To", before[-1])):
            k = f"{field}_{qid}_{ver}"
            value = getattr(proj, field) if getattr(proj, field) in before else default
            col.selectbox(label, before, index=before.index(value), key=k,
                          format_func=lambda x: Month.from_key(x).label, on_change=set_field, args=(qid, k, field))
        if not (proj.lookback_from and proj.lookback_to):
            proj.lookback_from, proj.lookback_to = before[0], before[-1]
            put(proj)
            st.rerun()

edit = show == "quarter"
if edit:
    shown, shown_proj = period, proj
else:
    m = Month.from_key(show)
    shown, shown_proj = Period("month", m.key, m.label, (m,)), scale_projection(proj, 1 / 3)
view: QuarterView = quarter_view(ds, shown_proj, shown, settings)
sug = quarter_suggestions(ds, proj, period, settings)

rev_id = state["rev"].get(qid)
saved = store.get_revision(rev_id) if rev_id else None
saved_txt = (f"Revision #{rev_id} saved {saved['saved_at']:%b %-d, %-I:%M %p}"
             + (f" by {h.esc(saved['saved_by'])}" if saved["saved_by"] else "")) if saved else "Not saved yet"
dirty = " · <b>Unsaved changes</b>" if state["dirty"].get(qid) else ""
when = ("Complete: all actuals are final." if period.end < ds.today else
        f"Revenue and KPIs through {ds.today:%b %-d}. Costs: {view.costs_label}." if period.start <= ds.today else
        "Future quarter.")
h.status(f"{when} · Suggestions learn from <b>{sug.window}</b> · % columns divide by revenue excl. "
         f"{', '.join(settings.get('pct_base_excluded_exits', []))} · {saved_txt}{dirty}")
if not edit:
    h.box("Monthly view: projections are the quarter ÷ 3. Switch to <b>Whole Quarter</b> to edit.", "info")
if not sug.months:
    h.box("No complete months with costs before this quarter, so every suggestion here shows "
          "<b>Insufficient Data</b>. That's expected for the first quarter after the start date.", "warn")

# ---------- prompts: an empty quarter, spend on sources that aren't projected
if edit and sug.months and not proj.marketing and not proj.revenue:
    with st.container(key="card-start"):
        st.html(f'<div class="sh"><span class="sec">Start</span><span class="t1">Start This Quarter</span>'
                f"<small>Nothing projected yet for {period.label}.</small></div>"
                f'<p class="status">Adds every marketing source with spend in {sug.window}, the exit strategies they '
                "closed under (and Follow Up for the rest), then fills in the suggested deals, deal sizes and "
                "budgets. You can change or remove anything afterwards.</p>")
        c = st.columns([2, 1.5, 3.5])
        c[0].button("Start From Suggestions", type="primary", icon=":material/auto_awesome:",
                    key=f"start_{qid}_{ver}", on_click=start_from_suggestions, args=(qid,))
        prev_rev = store.latest_revision(previous_quarter(qid))
        if c[1].button(f"Copy {previous_quarter(qid).replace('-', ' ')}", icon=":material/content_copy:",
                       disabled=prev_rev is None, key=f"copy0_{qid}_{ver}"):
            put(copy_lines(QuarterProjection.model_validate(prev_rev["payload"]), qid))
            st.rerun()
if edit and sug.months and (proj.marketing or proj.revenue):
    fresh = unprojected_spend(proj, ds, sug.months, settings)
    if fresh:
        h.box("<b>Spend found for sources you haven't projected:</b> "
              + " · ".join(f"{h.esc(s)} ({h.money(v)} in {sug.window})" for s, v in fresh.items())
              + ". It shows on “Other Marketing (Unprojected)” until you add them.", "info")
        with st.container(horizontal=True):
            for s in fresh:
                if st.button(f"Add {s}", icon=":material/add:", key=f"addfresh_{s}_{qid}_{ver}"):
                    put(add_source(proj, s))
                    st.rerun()

# ---------- actions
if edit:
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

# ---------- C: profit summary
h.heading("Profit Summary", "C", shown.label)
p_cost, p_rev = view.p_cost, view.p_revenue
in_progress = shown.start <= ds.today <= shown.end
tiles = [("Projected", h.money(view.p_profit),
          f"Revenue {h.money(p_rev)} − cost {h.money(p_cost)}<br>Margin {h.pct(view.p_margin)}")]
if in_progress:
    rp = daily_pace(shown, ds.today, p_rev, view.a_revenue)
    cp = cost_pace(shown, view.cost_months, p_cost, view.a_cost)
    share = min(100, view.a_revenue / p_rev * 100) if p_rev else 0
    mark = rp.expected_to_date / p_rev * 100 if p_rev else 0
    tiles.append((f"Revenue Pacing · {rp.basis}", h.money(view.a_revenue),
                  f"Expected by today {h.money(rp.expected_to_date)} ({h.pct(rp.pace_ratio)} of pace)"
                  f'<div class="meter"><i style="width:{share:.1f}%"></i><b style="left:{mark:.1f}%"></b></div>'))
    tiles.append(("Cost Pacing", h.money(view.a_cost) if view.cost_months else "No completed month yet",
                  f"{cp.basis}. Forecast {h.money(cp.forecast)}.", "" if view.cost_months else "muted"))
    tiles.append(("End-Of-Quarter Forecast", h.money(rp.forecast - cp.forecast),
                  f"Revenue at the current run rate {h.money(rp.forecast)} − cost {h.money(cp.forecast)}"
                  f"<br>vs projected profit {h.money(view.p_profit)}"))
else:
    tiles.append(("Actual", h.money(view.a_profit) if view.cost_months else "—",
                  f"Revenue {h.money(view.a_revenue_cost_months)} − cost {h.money(view.a_cost)}"
                  f"<br>Margin {h.pct(view.a_margin)} · {view.costs_label}"))
    gap = view.a_profit - view.p_profit
    tiles.append(("Projected Vs Actual", ("▲ " if gap >= 0 else "▼ ") + h.money(gap) if view.cost_months else "—",
                  f"Revenue {h.money(view.a_revenue - p_rev)} vs projection · cost "
                  f"{h.money(abs(p_cost - view.a_cost))} {'under' if p_cost >= view.a_cost else 'over'} budget",
                  ("up" if gap >= 0 else "down") if view.cost_months else "muted"))
tiles.append(("Cost %", h.pct(view.a_pct), f"Projected {h.pct(view.p_pct)} of revenue excl. "
              + ", ".join(settings.get("pct_base_excluded_exits", []))))
h.tiles(tiles)
rec = reconcile(ds, view)
if rec.ok:
    h.status(f"✓ Lines add up to the sheet: costs {h.money(rec.sheet_cost, 2)} ({view.costs_label}), revenue "
             f"{h.money(rec.sheet_revenue, 2)} from {rec.sheet_deals} deals.")
else:
    h.box(f"Lines don't add up to the sheet: costs {h.money(rec.lines_cost, 2)} vs {h.money(rec.sheet_cost, 2)}, "
          f"revenue {h.money(rec.lines_revenue, 2)} vs {h.money(rec.sheet_revenue, 2)}, deals {rec.lines_deals} vs "
          f"{rec.sheet_deals}.", "bad")


# ---------- A: costs
def cost_rows_html() -> str:
    """Read-only cost table: every line, then subtotals, as in the sheet."""
    has = bool(view.cost_months)

    def cells(label: str, p: float, a: float) -> list[str]:
        pp = p / view.p_base if view.p_base else None
        ap = a / view.a_base if view.a_base and has else None
        return [label, h.money(p), h.pct(pp), h.money(a) if has else '<span class="muted">not posted</span>',
                h.pct(ap), h.signed_cell(p - a if has else None),
                h.signed_cell(None if pp is None or ap is None else pp - ap, h.pct)]

    rows, classes = [], []
    groups = [("Marketing", [c for c in view.costs if c.kind != "non_marketing"]),
              ("Payroll", [c for c in view.costs if c.kind == "non_marketing" and c.source in payroll]),
              ("Other Costs", [c for c in view.costs if c.kind == "non_marketing" and c.source not in payroll])]
    for name, lines in groups:
        if not lines:
            continue
        rows.append(['<td colspan="7">' + name + "</td>"])
        classes.append("grp")
        for c in lines:
            label = h.esc(c.source) + (" " + h.pill("unprojected", "ins") if c.kind == OTHER_MARKETING else "")
            rows.append(cells(label, c.p_cost, c.a_cost))
            classes.append("")
        rows.append(cells(f"{name} Subtotal", sum(c.p_cost for c in lines), sum(c.a_cost for c in lines)))
        classes.append("sub")
    rows.append(cells("Total", view.p_cost, view.a_cost))
    classes.append("tot")
    return h.table(["Source", "P.Cost", "P.%", "A.Cost", "A.%", "PVA.Cost", "PVA.%"], rows, lambda n: classes[n])


def cost_editor(group: str, title: str) -> None:
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
        row |= {"A.Cost": x.a_cost, "Origin": ORIGIN[c.origin]}
        rows.append(row)
    subhead(title)
    if not rows:
        st.caption("No lines yet. Use Start From Suggestions above, or Add Source below.")
        return
    key = f"cost_{group}_{qid}_{ver}"
    st.data_editor(
        pd.DataFrame(rows), key=key, hide_index=True, width="stretch",
        disabled=["Source", "Suggested", "Implied Leads", "Implied Deals", "Notes", "A.Cost", "Origin"],
        column_config={"Remove": st.column_config.CheckboxColumn(width="small"), "P.Cost": MONEY, "A.Cost": MONEY,
                       "Suggested": st.column_config.NumberColumn(
                           format="dollar", help="Target deals × cost per deal over the suggestion window"),
                       "Accept": st.column_config.CheckboxColumn(width="small", help="Use the suggested budget"),
                       "Implied Leads": st.column_config.NumberColumn(format="%.0f", help="P.Cost ÷ CPL"),
                       "Implied Deals": st.column_config.NumberColumn(format="%.1f", help="Implied leads ÷ LPD"),
                       "Notes": st.column_config.TextColumn(width="medium")},
        on_change=apply_edits, args=(qid, key, group, list(range(len(lines))), {"P.Cost": "p_cost"}, suggestions))


h.heading("Costs", "A", "Type a projection or accept a suggestion. 🟠 = your override. PVA = projected − actual, "
          "green = under budget." if edit else "Projections are the quarter ÷ 3.")
if edit:
    cost_editor("marketing", "Marketing")
    if proj.marketing:
        c1, c2 = st.columns([1, 3], vertical_alignment="center")
        c1.button("Accept All Budgets", icon=":material/done_all:", key=f"acc_mkt_{qid}_{ver}",
                  on_click=fill, args=(qid, "marketing"),
                  help="Fills empty or previously accepted lines. Typed values are never replaced.")
        with c2.expander("How The Suggested Budgets Are Worked Out", icon=":material/function:"):
            st.caption("Budget = target deals × leads per deal × CPL = target deals × cost per deal. Target deals = "
                       "the source's P.Deals across all its revenue lines, so set revenue deals first.")
            for c in proj.marketing:
                s = sug.budgets.get(c.source)
                if s:
                    st.markdown(f"**{c.source}**\n" + "\n".join(f"- {line.replace('$', chr(92) + '$')}"
                                                              for line in s.explain()))
    other = next((c for c in view.costs if c.kind == OTHER_MARKETING), None)
    if other and other.contributors:
        with st.expander(f"Other Marketing (Unprojected) · {md_money(other.a_cost)}", icon=":material/campaign:"):
            for s, v in sorted(other.contributors.items(), key=lambda kv: -kv[1]):
                cc = st.columns([3, 2, 2], vertical_alignment="center")
                cc[0].write(s)
                cc[1].write(md_money(v))
                if cc[2].button("Add To Projection", key=f"addother_{s}_{qid}_{ver}"):
                    put(add_source(proj, s))
                    st.rerun()
    cost_editor("non_marketing", "Payroll And Other Costs (Manual Only)")
    with st.popover("Add Source", icon=":material/add:"):
        mkt = marketing_names(ds, settings)
        on = {c.source for c in proj.marketing + proj.non_marketing}
        pick = st.selectbox("From The Sheet", ["—"] + sorted(mkt - on), key=f"add_src_{qid}")
        typed = st.text_input("Or Type A Name", key=f"add_src_typed_{qid}",
                              help="Must match the COSTS / KPIs / REVENUES Source exactly to pick up actuals.")
        kind = st.segmented_control("Type", ["Marketing", "Non-Marketing"], default="Marketing",
                                    key=f"add_kind_{qid}")
        name = typed.strip() or (pick if pick != "—" else "")
        if st.button("Add", disabled=not name, key=f"add_src_btn_{qid}"):
            put(add_source(proj, name, marketing=kind != "Non-Marketing"))
            st.rerun()
h.show(cost_rows_html())

# ---------- B: revenue
h.heading("Revenue", "B", "Follow Up = every source without its own row in that block this quarter.")
actual_rev = {(x.block, x.source, x.exit): x for x in view.revenue if x.kind != UNPROJECTED}
for block in BLOCKS:
    subhead(BLOCK_LABELS[block])
    idx = [i for i, r in enumerate(proj.revenue) if r.block == block]
    lines = [x for x in view.revenue if x.block == block]
    if edit and idx:
        rows, rev_sug = [], {}
        for i in idx:
            r = proj.revenue[i]
            x = actual_rev.get((r.block, r.source, r.exit))
            s = sug.revenue.get((r.block, r.source, r.exit))
            rev_sug[i] = s
            rows.append({"Remove": False, "Source": r.source, "Exit": r.exit, "P.Deals": r.p_deals,
                         "P.Avg": r.p_avg, "Sugg. Deals": num(s.p_deals if s else None),
                         "Sugg. Avg": num(s.p_avg if s else None), "Accept": False, "P.Revenue": r.p_revenue,
                         "A.Deals": x.a_deals if x else 0, "A.Avg": num(x.a_avg if x else None),
                         "A.Revenue": x.a_revenue if x else 0.0, "Origin": ORIGIN[r.origin]})
        key = f"rev_{block}_{qid}_{ver}"
        st.data_editor(
            pd.DataFrame(rows), key=key, hide_index=True, width="stretch",
            disabled=["Source", "Exit", "Sugg. Deals", "Sugg. Avg", "P.Revenue", "A.Deals", "A.Avg", "A.Revenue",
                      "Origin"],
            column_config={"Remove": st.column_config.CheckboxColumn(width="small"), "P.Deals": COUNT,
                           "P.Avg": MONEY, "Sugg. Deals": st.column_config.NumberColumn(
                               format="%.2f", help="Deals in the window ÷ quarters in the window"),
                           "Sugg. Avg": st.column_config.NumberColumn(format="dollar", help="Window revenue ÷ deals"),
                           "Accept": st.column_config.CheckboxColumn(width="small", help="Use both suggested values"),
                           "P.Revenue": MONEY, "A.Avg": MONEY, "A.Revenue": MONEY},
            on_change=apply_edits, args=(qid, key, "revenue", idx, {"P.Deals": "p_deals", "P.Avg": "p_avg"}, rev_sug))
    if not edit and lines:
        h.show(h.table(["Source", "Exit Strategy", "P.Deals", "P.Avg", "P.Revenue", "A.Deals", "A.Avg", "A.Revenue"],
                       [[h.esc(x.label), h.esc(x.exit), h.num(x.p_deals, 2), h.money(x.p_avg), h.money(x.p_revenue),
                         str(x.a_deals), h.money(x.a_avg), h.money(x.a_revenue)] for x in lines],
                       lambda n, lines=lines: "auto" if lines[n].kind == UNPROJECTED else "", left=(0, 1)))
    projected = {(r.block, r.source, r.exit) for r in proj.revenue}
    loose = [x for x in lines if (x.block, x.source, x.exit) not in projected]
    if edit and loose:
        h.show(h.table(["Actuals Without A Projected Line", "Exit Strategy", "A.Deals", "A.Avg", "A.Revenue"],
                       [[h.esc(x.label) + " " + h.pill("unprojected", "ins"), h.esc(x.exit), str(x.a_deals),
                         h.money(x.a_avg), h.money(x.a_revenue)] for x in loose], lambda n: "auto", left=(0, 1)))
    fu = follow_up_sources(view, block)
    if len(fu):
        with st.expander(f"Follow Up Sources · {BLOCK_LABELS[block]}", icon=":material/call_split:"):
            h.show(h.table(["Exit Strategy", "Source", "Deals", "Revenue"],
                           [[h.esc(r.exit), h.esc(r.source), str(int(r.deals)), h.money(r.revenue)]
                            for r in fu.itertuples()], left=(0, 1)))
    if lines or idx:
        t_p, t_pd = sum(x.p_revenue for x in lines), sum(x.p_deals for x in lines)
        t_a, t_ad = sum(x.a_revenue for x in lines), sum(x.a_deals for x in lines)
        h.show(h.table([f"{BLOCK_LABELS[block]} Subtotal", "P.Deals", "P.Revenue", "A.Deals", "A.Revenue",
                        "PVA Revenue"], [["", h.num(t_pd, 2), h.money(t_p), str(t_ad), h.money(t_a),
                                          h.signed_cell(t_a - t_p)]], lambda n: "sub"))
    else:
        st.caption("No lines and no deals yet.")
h.show(h.table(["All Revenue (All Blocks)", "P.Deals", "P.Revenue", "A.Deals", "A.Revenue", "PVA Revenue"],
               [["", h.num(sum(x.p_deals for x in view.revenue), 2), h.money(view.p_revenue),
                 str(sum(x.a_deals for x in view.revenue)), h.money(view.a_revenue),
                 h.signed_cell(view.a_revenue - view.p_revenue)]], lambda n: "tot"))
if edit:
    c1, c2 = st.columns([1, 3], vertical_alignment="center")
    if proj.revenue:
        c1.button("Accept All Revenue", icon=":material/done_all:", key=f"acc_rev_{qid}_{ver}",
                  on_click=fill, args=(qid, "revenue"),
                  help="Fills empty or previously accepted lines. Typed values are never replaced.")
        with c2.expander("How The Suggested Revenue Is Worked Out", icon=":material/function:"):
            st.caption("P.Deals = deals in the window ÷ quarters in the window; P.Avg = window revenue ÷ window "
                       "deals (losses and $0 rows included). Follow Up pools the sources without a line in that block.")
            for (blk, src, ex), s in sug.revenue.items():
                pd_txt = f"{s.p_deals:.2f}" if s.p_deals is not None else "—"
                avg_txt = md_money(s.p_avg) if s.p_avg is not None else "no deals"
                st.markdown(f"- **{src} · {ex}** ({BLOCK_LABELS[blk]}): {s.deals} deals over {s.quarters:g} "
                            f"quarter(s) → {pd_txt} per quarter; avg {avg_txt}"
                            + (f" · from {', '.join(s.sources)}" if src == FOLLOW_UP and s.sources else ""))
    with st.popover("Add Revenue Line", icon=":material/add:"):
        blk = st.selectbox("Block", BLOCKS, format_func=BLOCK_LABELS.get, key=f"add_rev_block_{qid}")
        exits = [e for e in KNOWN_EXITS if block_of(e) == blk]
        sources = [FOLLOW_UP] + sorted({c.source for c in proj.marketing} | set(ds.revenues["source"]) - {""})
        src = st.selectbox("Source", sources, key=f"add_rev_src_{qid}")
        ex = st.selectbox("Exit Strategy", exits, key=f"add_rev_exit_{qid}")
        if st.button("Add", key=f"add_rev_btn_{qid}"):
            put(add_revenue_line(proj, blk, src, ex))
            st.rerun()

# ---------- D3: profit target
if edit:
    with st.container(key="card-d3"):
        h.heading("Profit Target", "D3", "Work backward from the profit you want to deals and budget per source.")
        t_key = f"target_{qid}_{ver}"
        tc = st.columns([1.3, 3], vertical_alignment="bottom")
        tc[0].number_input(f"Target Profit For {period.label}", min_value=0.0, step=10000.0, format="%.0f",
                           value=proj.profit_target, key=t_key, on_change=set_field,
                           args=(qid, t_key, "profit_target"), placeholder="e.g. 400000")
        if proj.profit_target is None:
            tc[1].caption("Payroll, consulting and general expenses stay fixed at what you projected; Follow Up, "
                          "Fix & Flip and Buy & Hold revenue stay at their projections.")
        elif not sug.months:
            tc[1].caption("No history window before this quarter, so plans can't be worked out.")
        else:
            fixed_costs, fixed_revenue = fixed_parts(proj)
            needed = needed_contribution(proj.profit_target, fixed_costs, fixed_revenue)
            tc[1].html(f'<p class="status">Fixed costs {h.money(fixed_costs)} · fixed revenue (Follow Up, Fix & Flip, '
                       f"Buy & Hold) {h.money(fixed_revenue)} · marketing sources must contribute "
                       f"<b>{h.money(needed)}</b> after their own budget.</p>")
            econ = source_economics(ds, proj, sug.months, settings)
            avg = {e.source: e.avg_deal for e in econ}
            cap = settings.get("scale_cap", 1.5)
            plans = ((plan_a(needed, econ), f"Fills the lowest cost-per-deal source first, up to {cap:g}× its best "
                      "quarter, then the next."),
                     (plan_b(needed, econ), "Scales your projected main-block deals by one factor across sources."))
            for col, (plan, desc) in zip(st.columns(2), plans, strict=True):
                with col:
                    k_txt = f" · ×{plan.k:.2f}" if plan.k is not None else ""
                    st.html(f'<div style="font-family:var(--display);font-size:17px;font-weight:700;'
                            f'color:var(--heading)">Plan {h.esc(plan.name)}{k_txt}</div>'
                            f'<p class="status">{desc}</p>')
                    rows = [[h.esc(x.source) + (" " + h.pill("over cap", "scale") if x.over_cap else ""),
                             h.num(x.deals, 1), h.money(x.budget), h.money(x.contribution)] for x in plan.lines]
                    rows.append(["Plan Total", "", h.money(plan.budget), h.money(plan.achieved)])
                    last = len(rows) - 1
                    h.show(h.table(["Source", "Deals", "Budget", "Contribution"], rows,
                                   lambda n, last=last: "tot" if n == last else ""))
                    if plan.shortfall > 0.5:
                        h.box(f"Short of target by {h.money(plan.shortfall)}: the usable sources hit their caps.",
                              "bad")
                    letter = plan.name.split(":")[0]
                    if plan.lines and st.button(f"Use Plan {letter} As Suggestions", key=f"use_{letter}_{qid}_{ver}",
                                                help="Sets those sources' deals and budgets; edit any cell to "
                                                     "override."):
                        put(apply_plan(proj, plan, avg))
                        st.rerun()

# ---------- month by month and history
with st.expander("Month By Month (Actuals)", icon=":material/calendar_month:"):
    st.dataframe(monthly_costs(ds, period), width="stretch",
                 column_config={c: MONEY for c in [*(m.label for m in period.months), "Total"]})
    mr = monthly_revenue(ds, period)
    st.dataframe(mr, width="stretch", column_config={c: MONEY for c in mr.columns if "revenue" in c})

with st.expander("History", icon=":material/history:"):
    quarters = store.list_quarters()
    if quarters:
        st.caption("Saved quarters: " + " · ".join(f"{q['quarter_id'].replace('-', ' ')} (updated "
                                                    f"{q['updated_at']:%b %-d})" for q in quarters))
    revs = store.list_revisions(qid)
    if not revs:
        st.caption("Nothing saved for this quarter yet.")
    else:
        st.dataframe(pd.DataFrame([{"Revision": r["id"], "Saved": f"{r['saved_at']:%b %-d, %Y %-I:%M %p}",
                                    "By": r["saved_by"], "Note": r["note"]} for r in revs]),
                     hide_index=True, width="stretch")
        pick = st.selectbox("Open A Revision", [r["id"] for r in revs], format_func=lambda i: f"#{i}",
                            key=f"hist_{qid}")
        if st.button("Open", key=f"hist_open_{qid}", help="Loads it as the working copy; save to make it current."):
            load(qid, store.get_revision(pick))
            state["dirty"][qid] = pick != revs[0]["id"]
            st.rerun()
