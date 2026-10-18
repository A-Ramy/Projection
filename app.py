"""Projection Tool (Total Cash Home Buyers): entry point.

    uv run streamlit run app.py
"""

import streamlit as st

from ui.brand import LOGO_MARK, inject
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

if not (get_secrets().has_sheet_access or demo_mode()):
    setup_screen()
    st.stop()

ds = get_dataset()
sidebar(ds, TOOLS)
tab_capsule(MAIN)
page.run()
