"""Projection Tool (Total Cash Home Buyers): entry point.

    uv run streamlit run app.py
"""

import streamlit as st

from ui.brand import LOGO_MARK, inject, logo
from ui.layout import setup_screen, sidebar, tab_capsule
from ui.state import demo_mode, get_dataset, get_secrets

st.set_page_config(page_title="Projection Tool · Total Cash Home Buyers", page_icon=str(LOGO_MARK), layout="wide")
inject()

MAIN = [
    st.Page("views/pta.py", title="PTA", icon=":material/groups:", url_path="pta"),
    st.Page("views/projections.py", title="Projections", icon=":material/request_quote:",
            url_path="projections", default=True),
    st.Page("views/funnel.py", title="Funnel", icon=":material/filter_alt:", url_path="funnel"),
]
TOOLS = [
    st.Page("views/data_quality.py", title="Data Quality", icon=":material/fact_check:", url_path="data-quality"),
    st.Page("views/settings.py", title="Settings", icon=":material/tune:", url_path="settings"),
    st.Page("views/backtest.py", title="Backtest", icon=":material/history:", url_path="backtest"),
]
page = st.navigation(MAIN + TOOLS, position="hidden")



def splash() -> None:
    """The logo alone, centered, with no sidebar: what the daily preview screenshot (shown on Streamlit's wake-up
    and loading screen) and the first data load show."""
    st.html("<style>[data-testid=stSidebar],[data-testid=stSidebarCollapsedControl],header{display:none!important}"
            ".block-container{padding-top:0!important}</style>")
    _, mid, _ = st.columns([1, 1.4, 1])
    mid.html('<div style="height:30vh"></div>')
    mid.image(logo(), width="stretch")


# Streamlit Community Cloud screenshots the app once a day with a headless browser and shows that picture while the
# app loads or wakes up: give it the logo. ?splash=1 shows the same screen for checking.
agent = st.context.headers.get("User-Agent", "") or ""
if st.query_params.get("splash") == "1" or ("HeadlessChrome" in agent and not demo_mode()):
    splash()
    st.stop()

if not (get_secrets().has_sheet_access or demo_mode()):
    setup_screen()
    st.stop()

loading = st.empty()
with loading.container():
    splash_shown = "dataset_ready" not in st.session_state
    if splash_shown:  # first load of the session: the logo while the sheet is read
        _, mid, _ = st.columns([1, 1.4, 1])
        mid.html('<div style="height:25vh"></div>')
        mid.image(logo(), width="stretch")
ds = get_dataset()
loading.empty()
st.session_state["dataset_ready"] = True
sidebar(ds, TOOLS)
tab_capsule(MAIN)
page.run()
