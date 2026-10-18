import streamlit as st

from ui.state import get_settings

st.title("Settings")
st.caption("Stored in the app's own database, never in the Google Sheet. Editing arrives with the Projections phase.")
s = get_settings()
st.write(f"**Start date:** {s['start_date']}")
st.write("**Non-marketing cost lines:** " + ", ".join(s["non_marketing"]))
st.write("**Revenue base for P.% and A.% excludes:** " + ", ".join(s["pct_base_excluded_exits"]))
st.write(f"**Low confidence below:** {s['low_conf_min_leads']} leads or {s['low_conf_min_deals']} deals")
st.write(f"**Scale warning above:** {s['scale_cap']}× a source's best quarter")
