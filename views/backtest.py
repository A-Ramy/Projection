"""Backtest: suggestions for a finished quarter made with only the months before it, compared with what happened."""

import streamlit as st

from projection.backtest import METRICS, backtest
from projection.periods import Month, period_of
from projection.suggest.lookback import LOOKBACKS
from ui import html as h
from ui.state import get_dataset, get_settings

ds = get_dataset()
if ds is None:
    st.stop()
settings = get_settings()

st.title("Backtest")
done = []
q = period_of(Month.of(ds.today), "quarter")
while True:
    q = period_of(q.months[0].add(-3), "quarter")
    if q.start < ds.start:
        break
    done.append(q)
if not done:
    h.box("No finished quarter after the start date yet.", "warn")
    st.stop()

c = st.columns([1.6, 2.4, 3], vertical_alignment="bottom")
by_key = {p.key: p for p in done}
target = by_key[c[0].segmented_control("Quarter", list(by_key), default=done[0].key, key="bt_quarter",
                                       format_func=lambda k: by_key[k].label) or done[0].key]
lookback = c[1].segmented_control("Learn From", [k for k in LOOKBACKS if k != "custom"], default="last_2_quarters",
                                  format_func=LOOKBACKS.get, key="bt_lookback") or "last_2_quarters"
basis = c[2].segmented_control("Budget Test", ["pred", "act"], default="pred",
                               format_func=lambda b: "Using Predicted Deals" if b == "pred"
                               else "Using The Quarter's Actual Deals") or "pred"
bt = backtest(ds, target, settings, lookback, actual_deals_basis=basis == "act")
h.status(f"Suggestions made with only <b>{bt.window_label}</b>, compared with what actually happened in "
         f"<b>{target.label}</b>. “Using the quarter's actual deals” tests the budget formula on its own.")
if not bt.window:
    h.box("No complete months before this quarter, so nothing can be predicted.", "warn")
    st.stop()


def err_cell(e) -> str:
    if e is None:
        return '<td class="muted">—</td>'
    k = "e-g" if abs(e) < 0.15 else "e-w" if abs(e) < 0.35 else "e-b"
    return f'<td><span class="err {k}">{e * 100:+.0f}%</span></td>'


FMT = {"budget": h.money, "leads": lambda v: h.num(v, 0), "deals": h.num, "revenue": h.money}
cols = ["Source"]
for m in METRICS:
    cols += [f"{m.title()} Pred.", "Actual", "Error"]
rows = []
for r in bt.rows:
    if not r.predictable:
        rows.append([h.esc(r.source), f'<td colspan="12" class="l muted">{r.note}, so no prediction. Actual: '
                     f"{h.money(r.actual_budget)} spend, {h.num(r.actual_leads, 0)} leads, {h.num(r.actual_deals)} "
                     "deals.</td>"])
        continue
    cells = [h.esc(r.source)]
    for m in METRICS:
        cells += [FMT[m](getattr(r, f"pred_{m}")), FMT[m](getattr(r, f"actual_{m}")), err_cell(r.error(m))]
    rows.append(cells)
total = ["Mean Abs. Error"]
for m in METRICS:
    v = bt.mape(m)
    total += ["", "", h.pct(v, 0)]
rows.append(total)
h.show(h.table(cols, rows, lambda n: "tot" if n == len(rows) - 1 else ""))
h.status("Green = within 15%, amber = within 35%, red = further off. Sources that started after the window can't be "
         "predicted from it.")
