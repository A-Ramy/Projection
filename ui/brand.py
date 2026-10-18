"""Total Cash Home Buyers brand: tokens per theme, the glass stylesheet, chart colors, and the theme toggle.

Tokens live here (one place for a rebrand); the rules that use them live in ui/brand.css. Light and dark are
Streamlit's own themes (.streamlit/config.toml), so widgets and tables switch too; this layer follows whichever
is active (st.context.theme.type).
"""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

CSS_FILE = Path(__file__).with_name("brand.css")
ASSETS = Path(__file__).resolve().parent.parent / "assets"
LOGO_MARK = ASSETS / "logo-mark.png"  # round mark: browser tab icon
LOGO = {"light": ASSETS / "logo-full.png", "dark": ASSETS / "logo-full-white.png"}

INDIGO, RED, STILETTO, GREEN = "#4D458A", "#BD2239", "#992849", "#109648"

TOKENS = {
    "light": {
        "bg": "#ffffff", "fg": "#211e33", "body": "#47445a", "heading": "#4d458a", "muted": "#767388",
        "line": "#eeedf2", "line-strong": "#c9c7d4", "accent": "#4d458a", "accent-soft": "#eae9f4",
        "on-accent": "#ffffff", "cta": "#bd2239", "cta-hover": "#992849", "money": "#109648",
        "good": "#0d7a3b", "good-bg": "#eaf7ef", "bad": "#bd2239", "bad-bg": "#fbf0f2", "warn": "#8a5a00",
        "warn-bg": "#fff3d1", "sub": "#f5f4fa", "ovr": "#b45309", "ovr-bg": "#fff1e0",
        "glass": "rgba(255,255,255,.58)", "glass-strong": "rgba(255,255,255,.82)",
        "glass-soft": "rgba(255,255,255,.40)",
        "glass-border": "rgba(255,255,255,.78)", "glass-line": "rgba(77,69,138,.13)",
        "glass-hi": "inset 0 1px 0 rgba(255,255,255,.95), inset 0 -1px 0 rgba(77,69,138,.06)",
        "glass-shadow": "0 8px 32px rgba(34,29,84,.11), 0 1px 3px rgba(34,29,84,.07)",
        "lift": "0 10px 26px rgba(34,29,84,.16)", "thumb": "rgba(255,255,255,.94)",
        "num-grad": "linear-gradient(120deg,#4d458a 10%,#7d3468 90%)",
        "bar-grad": "linear-gradient(90deg,#4d458a,#7b70d4)",
        "head-grad": "linear-gradient(180deg,#5d54a4 0%,#4d458a 60%,#423b78 100%)",
        "bg-glow-1": "rgba(98,90,165,.32)", "bg-glow-2": "rgba(189,34,57,.16)", "bg-glow-3": "rgba(16,150,72,.12)",
        "bg-base": "#f2f1f9", "sheen": "linear-gradient(180deg,rgba(255,255,255,.55),rgba(255,255,255,.12))",
    },
    "dark": {
        "bg": "#14122a", "fg": "#eceaf5", "body": "#d6d3e6", "heading": "#c4bff0", "muted": "#a19fb5",
        "line": "#2e2a4a", "line-strong": "#4a4568", "accent": "#a39ce3", "accent-soft": "#29254d",
        "on-accent": "#14122a", "cta": "#e0465a", "cta-hover": "#bd2239", "money": "#4cc27e",
        "good": "#5fd38a", "good-bg": "#12301f", "bad": "#ff7b86", "bad-bg": "#3a1620", "warn": "#f0c04f",
        "warn-bg": "#3a2f12", "sub": "#1b1832", "ovr": "#f5a35c", "ovr-bg": "#3a2510",
        "glass": "rgba(32,28,66,.52)", "glass-strong": "rgba(26,23,54,.84)", "glass-soft": "rgba(255,255,255,.07)",
        "glass-border": "rgba(255,255,255,.14)", "glass-line": "rgba(255,255,255,.08)",
        "glass-hi": "inset 0 1px 0 rgba(255,255,255,.16), inset 0 -1px 0 rgba(0,0,0,.25)",
        "glass-shadow": "0 10px 36px rgba(0,0,0,.45), 0 1px 3px rgba(0,0,0,.3)",
        "lift": "0 12px 30px rgba(0,0,0,.5)", "thumb": "rgba(255,255,255,.17)",
        "num-grad": "linear-gradient(120deg,#d9d4ff 10%,#f4a9bb 90%)",
        "bar-grad": "linear-gradient(90deg,#625aa5,#9d93f0)",
        "head-grad": "linear-gradient(180deg,#4f4790 0%,#3f387a 60%,#352f68 100%)",
        "bg-glow-1": "rgba(98,90,165,.40)", "bg-glow-2": "rgba(189,34,57,.24)", "bg-glow-3": "rgba(16,150,72,.15)",
        "bg-base": "#0d0b1f", "sheen": "linear-gradient(180deg,rgba(255,255,255,.10),rgba(255,255,255,.02))",
    },
}

# Categorical series colors, fixed order (validated for color-vision deficiency on each theme's surface).
SERIES = {
    "light": ["#4D458A", "#E8710A", "#1BAF7A", "#BD2239", "#2A78D6", "#EDA100"],
    "dark": ["#8A80E0", "#D95926", "#1EAF7C", "#C9304A", "#3987E5", "#C98500"],
}
OTHER = {"light": "#9A98A8", "dark": "#6B6886"}


def theme_type() -> str:
    try:
        return "dark" if st.context.theme.type == "dark" else "light"
    except Exception:
        return "light"


def logo() -> str:
    return str(LOGO[theme_type()])


def token(name: str) -> str:
    return TOKENS[theme_type()][name]


def series_colors(names: list[str]) -> dict[str, str]:
    """Colors follow the entity: the same name keeps its slot as long as the list order is stable.
    Beyond six series, the rest share the neutral 'other' color (and are labelled)."""
    pal, mode = SERIES[theme_type()], theme_type()
    return {n: pal[i] if i < len(pal) else OTHER[mode] for i, n in enumerate(names)}


def inject() -> None:
    """Theme tokens + the glass stylesheet. Call once per page run."""
    t = TOKENS[theme_type()]
    root = ":root{" + "".join(f"--{k}:{v};" for k, v in t.items()) + f"color-scheme:{theme_type()}}}"
    st.html(f"<style>{root}\n{CSS_FILE.read_text(encoding='utf-8')}</style>")


def theme_toggle() -> None:
    """Light / Dark switch. Streamlit keeps the theme per page in the browser, so the choice is written for
    every page and the page reloads once (unsaved projection edits are lost: save first)."""
    current = "Dark" if theme_type() == "dark" else "Light"
    choice = st.segmented_control("Theme", ["Light", "Dark"], default=current, key="theme_choice",
                                  label_visibility="collapsed", width="stretch")
    if choice and choice != current:
        components.html(f"""<script>
const w = window.parent, v = {json.dumps(json.dumps(choice))};
const paths = new Set(["/", "/pta", "/funnel", "/data-quality", "/settings", "/backtest", w.location.pathname]);
for (let i = 0; i < w.localStorage.length; i++) {{
  const k = w.localStorage.key(i);
  if (k && k.startsWith("stActiveTheme-") && k.endsWith("-v2")) paths.add(k.slice(14, -3));
}}
paths.forEach(p => w.localStorage.setItem("stActiveTheme-" + p + "-v2", v));
w.location.reload();
</script>""", height=0)


def plotly_layout() -> dict:
    """Recessive axes and grid, brand fonts, transparent surface (the glass card shows through)."""
    t = TOKENS[theme_type()]
    return dict(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Nunito Sans, sans-serif", color=t["muted"], size=12),
        margin=dict(l=8, r=8, t=8, b=8), hovermode="x unified",
        hoverlabel=dict(bgcolor=t["bg"], font=dict(color=t["fg"], family="Nunito Sans, sans-serif")),
        xaxis=dict(showgrid=False, linecolor=t["line-strong"], tickcolor=t["line-strong"]),
        yaxis=dict(gridcolor=t["line"], zeroline=False),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, font=dict(color=t["body"])),
    )
