"""Cached access to settings, storage and the cleaned dataset."""

from __future__ import annotations

import json
import os

import streamlit as st

from projection.config import Secrets, load_secrets
from projection.data.load import Dataset, build_dataset, load_dataset
from projection.storage import Store

CACHE_TTL_SECONDS = 600  # matches DEFAULT_SETTINGS["cache_ttl_minutes"]


def demo_mode() -> bool:
    """Developer preview with the test fixture instead of the live sheet (PROJECTION_DEMO=1)."""
    return os.environ.get("PROJECTION_DEMO") == "1"


@st.cache_resource
def get_secrets() -> Secrets:
    return load_secrets()


@st.cache_resource
def get_store() -> Store:
    return Store(get_secrets().database_url)


def get_settings() -> dict:
    return get_store().get_settings()


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner="Reading the Projection sheet…")
def _load(sheet_id: str, settings_json: str) -> Dataset:
    settings = json.loads(settings_json)
    if demo_mode():
        from tests.fixtures import TODAY, raw_sheet

        return build_dataset(raw_sheet(), settings, today=TODAY)
    return load_dataset(get_secrets(), settings)


def get_dataset() -> Dataset | None:
    """The cleaned 2026+ data, or None (with the reason shown) when it can't be read."""
    secrets = get_secrets()
    if not (secrets.has_sheet_access or demo_mode()):
        return None
    settings = get_settings()
    try:
        return _load(secrets.sheet_id, json.dumps(settings, sort_keys=True))
    except Exception as exc:  # show a usable message, never the key
        email = (secrets.service_account_info or {}).get("client_email", "the service account")
        text = str(exc)
        if "403" in text or "PERMISSION_DENIED" in text:
            st.error(f"The sheet isn't shared with **{email}**. In Google Sheets, click Share and add that "
                     "email as **Viewer**.")
        elif "404" in text or "not found" in text.lower():
            st.error("The sheet wasn't found. Check SHEET_ID in your settings.")
        else:
            st.error(f"Couldn't read the sheet: {type(exc).__name__}. Try Refresh data; if it persists, "
                     "check the service account setup.")
        return None


def refresh() -> None:
    _load.clear()
