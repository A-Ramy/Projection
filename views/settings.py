"""Settings: stored in the app's own database (never in the Google Sheet)."""

from datetime import date

import streamlit as st
from streamlit_sortables import sort_items

from projection.config import DEFAULT_SETTINGS
from projection.data.schema import KNOWN_EXITS
from projection.suggest.lookback import LOOKBACKS
from ui import html as h
from ui.brand import sortable_style
from ui.state import get_dataset, get_settings, get_store, refresh

st.title("Settings")
h.status("Stored in the app's own database, never in the Google Sheet. Changes apply to everyone.")

s = get_settings()
ds = get_dataset()
cost_names = sorted(set(ds.costs["source"])) if ds is not None else []
names = sorted(set(cost_names) | set(s["non_marketing"]))
all_sources = set() if ds is None else (set(ds.costs["source"]) | set(ds.revenues["source"]) | set(ds.leads["source"]))
src_names = sorted((all_sources - set(s["non_marketing"]) - {""}) | set(s["active_sources"]))

with st.form("settings"), st.container(key="card-settings"):
    start = st.date_input("Start Date", value=date.fromisoformat(s["start_date"]), format="YYYY-MM-DD",
                          help="No calculation, lookback or suggestion uses data before this date.")
    excl = st.multiselect("Revenue Base For P.% And A.% Excludes", KNOWN_EXITS, default=s["pct_base_excluded_exits"],
                          help="Both P.% and A.% divide by total revenue minus these exit strategies.")
    non = st.multiselect("Non-Marketing Cost Lines", names, default=s["non_marketing"],
                         help="Every other COSTS name is a marketing source. New names default to marketing.")
    payroll = st.multiselect("Of Which Payroll", names, default=[p for p in s["payroll"] if p in names],
                             help="Grouped as Payroll on the Projections tab.")
    active = st.multiselect("Active Sources (Projected On Their Own)", src_names, default=s["active_sources"],
                            accept_new_options=True,
                            help="Each gets its own row on Projections; every other source is projected as part of "
                                 "Follow Up. Names must match the sheet exactly (you can type a new one).")
    lb = st.selectbox("Default Suggestion Window", list(LOOKBACKS), index=list(LOOKBACKS).index(s["lookback_default"]),
                      format_func=LOOKBACKS.get, help="New quarters start with this; each quarter can change it.")
    c = st.columns(3)
    min_leads = c[0].number_input("Low Confidence Below (Leads)", min_value=0, value=int(s["low_conf_min_leads"]))
    min_deals = c[1].number_input("Low Confidence Below (Deals)", min_value=0, value=int(s["low_conf_min_deals"]))
    cap = c[2].number_input("Scale Warning Above (× Best Quarter)", min_value=1.0, step=0.1,
                            value=float(s["scale_cap"]))
    c = st.columns(3)
    immature = c[0].number_input("Cohorts Flagged As Recent (Months)", min_value=0,
                                 value=int(s["cohort_immature_months"]))
    ttl = c[1].number_input("Reload Data After (Minutes)", min_value=1, value=int(s["cache_ttl_minutes"]))
    saved = st.form_submit_button("Save Settings", type="primary", icon=":material/save:")


def user_email() -> str:
    try:
        return st.user.email or ""
    except Exception:
        return ""


if saved:
    who = user_email()
    new = {"start_date": start.isoformat(), "pct_base_excluded_exits": excl, "non_marketing": non,
           "payroll": payroll, "active_sources": active, "lookback_default": lb, "low_conf_min_leads": int(min_leads),
           "low_conf_min_deals": int(min_deals), "scale_cap": float(cap), "cohort_immature_months": int(immature),
           "cache_ttl_minutes": int(ttl)}
    store = get_store()
    for k, v in new.items():
        if v != s.get(k):
            store.set_setting(k, v, by=who)
    refresh()  # the start date and classifications change what's loaded
    st.toast("Settings saved", icon=":material/check:")
    st.rerun()

st.subheader("Source Order")
h.status("The order new quarters start in on Projections (each quarter can still be dragged into its own order). "
         "Drag a source up or down; it saves straight away.")
with st.container(key="card-order"):
    order = sort_items(list(s["active_sources"]), direction="vertical", custom_style=sortable_style(),
                       key="active_order_" + "|".join(s["active_sources"]))
    if order != s["active_sources"]:
        get_store().set_setting("active_sources", order, by=user_email())
        st.toast("Source order saved", icon=":material/check:")
        st.rerun()
    if s["active_sources"] != DEFAULT_SETTINGS["active_sources"] and st.button(
            "Use The Built-In List And Order", icon=":material/restart_alt:",
            help=", ".join(DEFAULT_SETTINGS["active_sources"])):
        get_store().set_setting("active_sources", DEFAULT_SETTINGS["active_sources"], by=user_email())
        refresh()
        st.rerun()

with st.expander("Defaults", icon=":material/restart_alt:"):
    st.json({k: v for k, v in DEFAULT_SETTINGS.items()})
