"""Cell- and row-level parsing of raw Sheets API values.

Values arrive UNFORMATTED (numbers for money, serial numbers for dates) but text cells are also
accepted ("$1,234.56", "1/31/2026"), because hand-typed cells can be text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from projection.data.schema import Issue

SHEETS_EPOCH = datetime(1899, 12, 30)  # Google Sheets / Excel serial day 0
_DATE_FORMATS = ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d")


class CellError(ValueError):
    pass


def is_blank(value) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def to_datetime(value) -> datetime | None:
    if is_blank(value):
        return None
    if isinstance(value, bool):
        raise CellError(f"not a date: {value!r}")
    if isinstance(value, (int, float)):
        return SHEETS_EPOCH + timedelta(days=float(value))
    text = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise CellError(f"not a date: {text!r}")


_MONEY_STRIP = re.compile(r"[\s$,]")


def to_money(value) -> float | None:
    if is_blank(value):
        return None
    if isinstance(value, bool):
        raise CellError(f"not an amount: {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("−", "-")  # unicode minus
    negative = text.startswith("(") and text.endswith(")")
    text = _MONEY_STRIP.sub("", text.strip("()"))
    if text.startswith("-"):
        negative, text = True, text[1:]
    try:
        amount = float(text)
    except ValueError as exc:
        raise CellError(f"not an amount: {value!r}") from exc
    return -amount if negative else amount


def to_text(value) -> str:
    """Cell as text, exactly as written apart from None -> "". Names are joined on exact text."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _norm_header(h) -> str:
    return re.sub(r"\s+", " ", to_text(h)).strip().casefold()


@dataclass
class TabRows:
    tab: str
    records: list[dict]  # raw cell values keyed by field name, plus "sheet_row"
    blank_rows: int
    issues: list[Issue]


def rows_to_records(tab: str, values: list[list], columns: dict[str, str]) -> TabRows:
    """Map rows to field dicts by header name. Fully blank rows (month separators) are counted."""
    issues: list[Issue] = []
    if not values:
        issues.append(Issue("error", tab, "empty_tab", f"{tab} returned no rows"))
        return TabRows(tab, [], 0, issues)

    header = [_norm_header(h) for h in values[0]]
    col_index: dict[str, int] = {}
    missing = []
    for fld, name in columns.items():
        try:
            col_index[fld] = header.index(_norm_header(name))
        except ValueError:
            missing.append(name)
    if missing:
        issues.append(
            Issue(
                "error",
                tab,
                "missing_columns",
                f"{tab} is missing expected column(s)",
                detail="Expected headers: " + ", ".join(columns.values()),
                count=len(missing),
                examples=missing,
            )
        )

    records, blank = [], 0
    for i, row in enumerate(values[1:], start=2):  # sheet row numbers start at 1 (header)
        if all(is_blank(v) for v in row):
            blank += 1
            continue
        rec = {fld: (row[idx] if idx < len(row) else None) for fld, idx in col_index.items()}
        rec["sheet_row"] = i
        records.append(rec)
    return TabRows(tab, records, blank, issues)
