"""Cached access to settings, storage and the cleaned dataset."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from projection.config import Secrets, load_secrets
from projection.data.load import Dataset, build_dataset, scrub
from projection.sheets import RawSheet, fetch_raw
from projection.storage import Store


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


@st.cache_data(max_entries=2, show_spinner="Reading the Projection sheet…")
def _raw(sheet_id: str, window: int) -> tuple[RawSheet, datetime]:
    """One read of the sheet per reload window (setting cache_ttl_minutes), GHL links already hashed."""
    if demo_mode():
        from tests.metrics_fixture import raw_sheet

        return raw_sheet(), datetime.now()
    raw = scrub(fetch_raw(get_secrets()))
    return raw, datetime.now(ZoneInfo(raw.timezone or "America/New_York"))


@st.cache_data(max_entries=4, show_spinner="Preparing the data…")
def _build(sheet_id: str, window: int, settings_json: str) -> Dataset:
    """The cleaned data for these settings; a settings change rebuilds it without reading the sheet again."""
    raw, fetched = _raw(sheet_id, window)
    today = None
    if demo_mode():
        from tests.metrics_fixture import TODAY

        today = TODAY
    return build_dataset(raw, json.loads(settings_json), today=today, fetched_at=fetched)


def _load(sheet_id: str, settings: dict) -> Dataset:
    minutes = max(1, int(settings.get("cache_ttl_minutes", 10)))
    window = int(time.time() // (minutes * 60))
    return _build(sheet_id, window, json.dumps(settings, sort_keys=True))


def get_dataset() -> Dataset | None:
    """The cleaned 2026+ data, or None (with the reason shown) when it can't be read."""
    secrets = get_secrets()
    if not (secrets.has_sheet_access or demo_mode()):
        return None
    settings = get_settings()
    try:
        return _load(secrets.sheet_id, settings)
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
    _raw.clear()
    _build.clear()
