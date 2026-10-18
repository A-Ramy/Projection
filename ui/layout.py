"""Shared page pieces: sidebar status, setup screen, issue list."""

from __future__ import annotations

import streamlit as st

from projection.data.load import Dataset
from projection.data.schema import Issue
from ui.state import demo_mode, get_secrets, refresh

SEVERITY = {"error": ("Error", ":material/error:"), "warning": ("Check", ":material/warning:"),
            "info": ("Info", ":material/info:")}


def sidebar(ds: Dataset | None) -> None:
    with st.sidebar:
        st.markdown("### Total Cash Home Buyers\nProjection Tool")
        st.caption("Data source")
        st.markdown("Google Sheet **Projection** · read-only")
        if ds is not None:
            st.caption(f"Data from {ds.start:%b %-d, %Y} onward · refreshed {ds.fetched_at:%-I:%M %p}")
        if demo_mode():
            st.warning("Sample data (developer preview)")
        if st.button("Refresh data", icon=":material/refresh:", width="stretch"):
            refresh()
            st.rerun()


def setup_screen() -> None:
    st.title("Connect the Projection sheet")
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
    for i in (i for i in issues if i.severity in severities):
        label, icon = SEVERITY.get(i.severity, ("Info", ":material/info:"))
        title = f"{label} · {i.title}" + (f" ({i.count:,})" if i.count else "")
        with st.expander(title, icon=icon, expanded=i.severity == "error"):
            if i.detail:
                st.write(i.detail)
            if i.examples:
                st.markdown("\n".join(f"- {e}" for e in i.examples))
            st.caption(f"Tab: {i.tab}")
