"""Small HTML builders for the read-only, sheet-style parts of the pages (styled by ui/brand.css)."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from html import escape

import streamlit as st


def ok(v) -> bool:
    return v is not None and not (isinstance(v, float) and math.isnan(v))


def money(v, decimals: int = 0) -> str:
    if not ok(v):
        return "—"
    return f"{'−' if v < 0 else ''}${abs(v):,.{decimals}f}"


def pct(v, decimals: int = 1) -> str:
    return f"{v * 100:.{decimals}f}%" if ok(v) else "—"


def num(v, decimals: int = 1) -> str:
    if not ok(v):
        return "—"
    return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.{decimals}f}"


def esc(s) -> str:
    return escape(str(s))


def pill(text: str, kind: str = "ok") -> str:
    return f'<span class="pill p-{kind}">{esc(text)}</span>'


def sw(color: str) -> str:
    return f'<span class="sw" style="background:{color}"></span>'


def heading(title: str, badge: str | None = None, note: str = "") -> None:
    st.html(f'<div class="sh">{f"<span class=sec>{esc(badge)}</span>" if badge else ""}'
            f'<span class="t1">{esc(title)}</span>{f"<small>{note}</small>" if note else ""}</div>')


def box(text: str, kind: str = "info") -> None:
    st.html(f'<div class="box {kind}">{text}</div>')


def status(text: str) -> None:
    st.html(f'<p class="status">{text}</p>')


def tiles(items: Iterable[tuple[str, str, str] | tuple[str, str, str, str]]) -> None:
    """(label, value, sub[, value class]) per tile; sub may contain HTML."""
    out = []
    for item in items:
        label, value, sub, cls = (*item, "")[:4]
        out.append(f'<div class="tile"><span class="l">{esc(label)}</span><span class="v {cls}">{esc(value)}</span>'
                   f'<span class="s">{sub}</span></div>')
    st.html(f'<div class="tiles">{"".join(out)}</div>')


def table(columns: list[str], rows: Iterable[list[str]], row_class: Callable[[int], str] | None = None,
          left: Iterable[int] = (0,), cls: str = "", click: Callable[[int], str | None] | None = None) -> str:
    """Cells are HTML strings (escape data with esc()). Returns the HTML so callers can combine pieces.
    click(n) gives a row's click value (rendered with ui.clicktable.clickable)."""
    left = set(left)
    head = "".join(f'<th class="{"l" if i in left else ""}">{esc(c)}</th>' for i, c in enumerate(columns))
    body = []
    for n, r in enumerate(rows):
        rc = row_class(n) if row_class else ""
        cells = "".join(c if c.startswith("<td") else f'<td class="{"l" if i in left else ""}">{c}</td>'
                        for i, c in enumerate(r))
        cv = click(n) if click else None
        attr = f' data-click="{esc(cv)}"' if cv else ""
        body.append(f'<tr class="{rc}"{attr}>{cells}</tr>')
    return (f'<div class="wrap"><table class="t {cls}"><thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def show(html: str) -> None:
    st.html(html)


def signed_cell(v, fmt: Callable = money) -> str:
    """A PVA-style cell: green when ≥ 0, red when < 0."""
    if not ok(v):
        return '<td class="muted">—</td>'
    return f'<td class="{"pos" if v >= 0 else "neg"}">{fmt(v)}</td>'


def arrow(cur, prev) -> str:
    """Change vs the previous period; none when either side is 0 (a drop to nothing is shown by the 0 itself)."""
    if not (ok(cur) and ok(prev)) or prev == 0 or cur == 0:
        return ""
    d = (cur - prev) / abs(prev)
    return f' <span class="{"up" if d >= 0 else "down"}">{"▲" if d >= 0 else "▼"}{abs(d) * 100:.0f}%</span>'
