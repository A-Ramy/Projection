"""Shared page pieces: branded sidebar, the tab capsule, setup screen, issue cards."""

from __future__ import annotations

import streamlit as st

from projection.data.load import Dataset
from projection.data.schema import Issue
from ui import html as h
from ui.brand import logo, theme_toggle
from ui.state import demo_mode, get_secrets, refresh

SEVERITY = {"error": ("Error", "scale"), "warning": ("Check", "low"), "info": ("Info", "ins")}


def sidebar(ds: Dataset | None, tools: list) -> None:
    with st.sidebar:
        st.image(logo(), width="stretch")
        st.html('<div class="brand-sub">Projection Tool</div>')
        theme_toggle()
        st.html('<div class="side-h">Data Source</div>')
        refreshed = f"<span>Refreshed {ds.fetched_at:%-I:%M %p}</span>" if ds is not None else ""
        start = f"<span>{ds.start:%b %-d, %Y} onward</span>" if ds is not None else ""
        st.html(f'<div class="kv"><span>Google Sheet <b>Projection</b></span><span>Read-only · service account</span>'
                f"{start}{refreshed}</div>")
        if demo_mode():
            st.warning("Sample data (developer preview)")
        if st.button("Refresh Data", icon=":material/refresh:", width="stretch"):
            refresh()
            st.rerun()
        st.html('<div class="side-h">Tools</div>')
        checks = sum(1 for i in ds.issues if i.severity in ("error", "warning")) if ds is not None else 0
        for p in tools:
            label = f"{p.title} ({checks})" if p.url_path == "data-quality" and checks else p.title
            st.page_link(p, label=label, width="stretch")
        st.html('<div class="kv" style="margin-top:14px"><span>Private app</span>'
                "<span>Invited team members only</span></div>")


def tab_capsule(pages: list) -> None:
    with st.container(key="tabs", horizontal=True, width="content", gap=None):
        for p in pages:
            st.page_link(p)


def setup_screen() -> None:
    st.title("Connect The Projection Sheet")
    st.write("The app reads the Google Sheet through a read-only service account. It isn't configured yet.")
    st.markdown(
        """
1. In the Google Cloud console, create a project and enable the **Google Sheets API**.
2. Create a service account (no roles), then **Keys → Add key → JSON**.
3. Share the **Projection** sheet with the service account's email as **Viewer**.
4. Base64-encode the key (`base64 -w0 key.json`) and set it as `GOOGLE_SERVICE_ACCOUNT_JSON_B64`:
   in `.env` locally, or under **Secrets** on Streamlit Community Cloud.
5. Reload this page.
"""
    )
    st.caption(f"Sheet ID: {get_secrets().sheet_id}")


def issue_list(issues: list[Issue], severities: tuple[str, ...] = ("error", "warning", "info")) -> None:
    cards = []
    for i in (i for i in issues if i.severity in severities):
        label, kind = SEVERITY.get(i.severity, ("Info", "ins"))
        examples = "".join(f"<li>{h.esc(e)}</li>" for e in i.examples)
        cards.append(
            f'<div class="it"><div>{h.pill(label, kind)}<br><span class="muted" style="font-size:13px">{h.esc(i.tab)}'
            f'</span></div><div><b>{h.esc(i.title)}</b>{f" ({i.count:,})" if i.count else ""}'
            f'{f"<br><span class=muted>{h.esc(i.detail)}</span>" if i.detail else ""}'
            f'{f"<ul>{examples}</ul>" if examples else ""}</div></div>')
    st.html(f'<div class="dq">{"".join(cards)}</div>' if cards else '<p class="status">Nothing to report.</p>')
