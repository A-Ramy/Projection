"""A read-only sheet-style table (ui.html.table) whose marked rows can be clicked. Returns the clicked row's value once
per click (None otherwise). Rows are marked with ui.html.table(..., click=...)."""

from __future__ import annotations

from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from ui.brand import CSS_FILE, TOKENS, theme_type

_component = components.declare_component("clicktable", path=str(Path(__file__).with_name("components") / "clicktable"))
FONTS = ("@import url('https://fonts.googleapis.com/css2?family=Nunito+Sans:opsz,wght@6..12,400;6..12,600;6..12,700"
         "&family=Baloo+2:wght@600;700&display=swap');")


def clickable(html: str, key: str, hint: str = "") -> str | None:
    t = TOKENS[theme_type()]
    root = ":root{" + "".join(f"--{k}:{v};" for k, v in t.items()) + f"color-scheme:{theme_type()}}}"
    css = FONTS + root + CSS_FILE.read_text(encoding="utf-8") + "body{font-family:var(--font);background:transparent}"
    value = _component(html=html, css=css, hint=hint, key=key, default=None)
    if not value or st.session_state.get(f"{key}_seen") == value.get("at"):
        return None
    st.session_state[f"{key}_seen"] = value.get("at")
    return value.get("row")
