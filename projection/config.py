"""Configuration: secrets come from env vars / .env first, then Streamlit secrets.

Business settings (start date, non-marketing names, thresholds...) have defaults here and are
overridden by values saved in the app's own storage (see storage.py), never in the Google Sheet.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / ".data"

DEFAULT_SHEET_ID = "19RJ-hCH0rlOXJpHrnjDY_j_cDu_N4nA2uUuVxagQues"
SHEETS_SCOPES = ("https://www.googleapis.com/auth/spreadsheets.readonly",)

# Editable in Settings; stored in the app database. Keys are stable identifiers.
DEFAULT_SETTINGS: dict = {
    "start_date": "2026-01-01",
    "non_marketing": [
        "ACQ Payroll",
        "OPS Payroll",
        "TC Payroll",
        "DISPO Payroll",
        "CONSULTING",
        "General Expenses",
    ],
    "payroll": ["ACQ Payroll", "OPS Payroll", "TC Payroll", "DISPO Payroll"],
    # No-cost sources projected on their own (by revenue or deals) next to the marketing sources; every other
    # no-cost source is projected as part of Follow Up.
    "own_no_cost_sources": ["SELF GEN", "Referral"],
    # Revenue base for P.% and A.%: total revenue minus these exit strategies.
    "pct_base_excluded_exits": ["Fix & Flip", "Buy & Hold"],
    "low_conf_min_leads": 30,
    "low_conf_min_deals": 3,
    "scale_cap": 1.5,
    "lookback_default": "last_quarter",  # last_quarter | last_2_quarters | all | custom
    "cohort_immature_months": 2,  # recent cohorts flagged as not yet mature
    "cache_ttl_minutes": 10,
}


@dataclass(frozen=True)
class Secrets:
    sheet_id: str
    service_account_info: dict | None
    database_url: str | None

    @property
    def has_sheet_access(self) -> bool:
        return self.service_account_info is not None


def _streamlit_secrets() -> dict:
    """Streamlit secrets if running under Streamlit and a secrets file exists; else {}."""
    try:
        import streamlit as st

        return dict(st.secrets)
    except Exception:
        return {}


def _decode_service_account(raw_b64: str | None, table: dict | None) -> dict | None:
    if table:
        return dict(table)
    if not raw_b64:
        return None
    try:
        return json.loads(base64.b64decode(raw_b64).decode("utf-8"))
    except Exception as exc:  # never echo the value itself
        raise ValueError(
            "GOOGLE_SERVICE_ACCOUNT_JSON_B64 is set but is not valid base64-encoded JSON."
        ) from exc


def load_secrets() -> Secrets:
    load_dotenv(ROOT / ".env", override=False)
    st_secrets = _streamlit_secrets()

    def get(key: str) -> str | None:
        return os.environ.get(key) or (str(st_secrets[key]) if key in st_secrets else None) or None

    info = _decode_service_account(
        get("GOOGLE_SERVICE_ACCOUNT_JSON_B64"), st_secrets.get("gcp_service_account")
    )
    return Secrets(
        sheet_id=get("SHEET_ID") or DEFAULT_SHEET_ID,
        service_account_info=info,
        database_url=get("DATABASE_URL"),
    )


def parse_start_date(settings: dict) -> date:
    return date.fromisoformat(settings.get("start_date") or DEFAULT_SETTINGS["start_date"])
