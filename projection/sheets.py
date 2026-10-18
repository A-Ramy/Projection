"""Read-only Google Sheets access through a service account.

Only the `spreadsheets.readonly` scope is requested; the service account should also be shared on
the sheet as Viewer, so read-only is enforced on Google's side too. Nothing here writes.
"""

from __future__ import annotations

from dataclasses import dataclass

import gspread
from google.oauth2.service_account import Credentials

from projection.config import SHEETS_SCOPES, Secrets
from projection.data.schema import RANGES, TAB_KPIS


@dataclass
class RawSheet:
    values: dict[str, list[list]]  # range name -> rows (first row = header)
    timezone: str


def _client(secrets: Secrets) -> gspread.Client:
    if not secrets.service_account_info:
        raise RuntimeError("No service account configured (GOOGLE_SERVICE_ACCOUNT_JSON_B64).")
    creds = Credentials.from_service_account_info(secrets.service_account_info, scopes=list(SHEETS_SCOPES))
    return gspread.authorize(creds)


def fetch_raw(secrets: Secrets) -> RawSheet:
    """One batch read of the needed ranges, as unformatted values with serial-number dates."""
    sh = _client(secrets).open_by_key(secrets.sheet_id)
    names, ranges = list(RANGES), list(RANGES.values())
    resp = sh.values_batch_get(
        ranges, params={"valueRenderOption": "UNFORMATTED_VALUE", "dateTimeRenderOption": "SERIAL_NUMBER"}
    )
    value_ranges = resp.get("valueRanges", [])
    values = {name: (vr.get("values") or []) for name, vr in zip(names, value_ranges, strict=False)}
    return RawSheet(values=values, timezone=sh.timezone or "America/New_York")


def fetch_contact_details(secrets: Secrets, sheet_rows: list[int]) -> dict[int, dict]:
    """Explicit drill-down only: Full Name, Phone, GHL Link for specific KPI rows, fetched live.

    Never cached, logged or stored. Callers must only display the result on screen.
    """
    rows = sorted({int(r) for r in sheet_rows if int(r) > 1})[:50]
    if not rows:
        return {}
    sh = _client(secrets).open_by_key(secrets.sheet_id)
    resp = sh.values_batch_get([f"{TAB_KPIS}!K{r}:M{r}" for r in rows])
    out = {}
    for r, vr in zip(rows, resp.get("valueRanges", []), strict=False):
        cells = (vr.get("values") or [[]])[0] + ["", "", ""]
        out[r] = {"Full Name": cells[0], "Phone": cells[1], "GHL Link": cells[2]}
    return out
