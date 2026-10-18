"""Records -> clean DataFrames. The start-date filter is applied first, row by row.

Every row is assigned to a calendar month ('YYYY-MM'). COSTS dates are month totals (sometimes
dated the 27th or 30th), so their exact day is ignored after bucketing.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from projection.data.keys import addr_key, lead_key
from projection.data.parse import CellError, TabRows, is_blank, to_datetime, to_money, to_text
from projection.data.schema import LEAD_KPI, TAB_COSTS, TAB_KPIS, TAB_REVENUES, Issue
from projection.funnel_config import KPI_STAGES
from projection.periods import Month

COSTS_FRAME = ["date", "month", "source", "cost", "cost_blank", "sheet_row"]
REVENUES_FRAME = [
    "date", "month", "address", "addr_key", "source", "revenue", "revenue_blank", "exit",
    "agent", "fus", "acq", "dispo", "dispo_lm", "sheet_row",
]
KPIS_FRAME = [
    "date", "month", "created", "kpi", "quality", "stage", "acq", "source", "fus", "lead_agent",
    "addr_key", "lead_key", "sheet_row",
]
# One row per KPI = Lead row, counted in All Leads by Date Created (date = Quality-change date, NaT = Pending)
LEADS_FRAME = [
    "created", "month", "date", "quality", "source", "acq", "fus", "lead_agent", "addr_key", "lead_key",
    "sheet_row",
]
_STAGE_SPELLING = {s.casefold(): s for s in KPI_STAGES}


def canonical_kpi(kpi: str) -> str:
    """KPI values match funnel stages case-insensitively ("No-Show" -> "No-show")."""
    return _STAGE_SPELLING.get(kpi.casefold(), kpi)


@dataclass
class TabStats:
    rows_with_content: int = 0
    blank_rows: int = 0  # separator rows, plus date-only filler rows
    before_start: int = 0
    kept: int = 0


@dataclass
class BlankKpiDates:
    count: int = 0
    by_quality: Counter = field(default_factory=Counter)
    by_kpi: Counter = field(default_factory=Counter)
    created_since_start: int = 0
    leads_counted: int = 0  # blank-Date (Pending) Lead rows counted in All Leads by Date Created


class _Bad:
    """Collects unparseable cells per tab into one Issue."""

    def __init__(self, tab: str):
        self.tab, self.examples, self.count = tab, [], 0

    def add(self, row: int, col: str, err: Exception):
        self.count += 1
        if len(self.examples) < 8:
            self.examples.append(f"row {row}, {col}: {err}")

    def issue(self) -> list[Issue]:
        if not self.count:
            return []
        return [Issue("error", self.tab, "unparseable_cells", f"{self.tab}: cells that couldn't be read",
                      detail="These rows were skipped. Fix the cell format in the sheet.",
                      count=self.count, examples=self.examples)]


def _frame(rows: list[dict], columns: list[str], date_cols: tuple[str, ...]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=columns)
    for c in date_cols:
        df[c] = pd.to_datetime(df[c])
    return df


def clean_costs(tr: TabRows, start: date) -> tuple[pd.DataFrame, TabStats, list[Issue]]:
    stats, bad, rows = TabStats(blank_rows=tr.blank_rows), _Bad(TAB_COSTS), []
    undated, no_source = [], []
    for rec in tr.records:
        r = rec["sheet_row"]
        src, raw_cost = to_text(rec.get("source")), rec.get("cost")
        try:
            d = to_datetime(rec.get("date"))
        except CellError as e:
            bad.add(r, "Date", e)
            continue
        if is_blank(src) and is_blank(raw_cost):
            stats.blank_rows += 1  # e.g. "1/31/2025,," filler lines
            continue
        stats.rows_with_content += 1
        if d is None:
            undated.append(f"row {r}: {src or '(no source)'}")
            continue
        if d.date() < start:
            stats.before_start += 1
            continue
        try:
            cost = to_money(raw_cost)
        except CellError as e:
            bad.add(r, "Cost", e)
            continue
        if is_blank(src):
            no_source.append(f"row {r}: {cost}")
            continue
        rows.append({"date": d, "month": Month.of(d).key, "source": src, "cost": cost or 0.0,
                     "cost_blank": cost is None, "sheet_row": r})
    issues = bad.issue()
    if undated:
        issues.append(Issue("warning", TAB_COSTS, "undated_rows", "COSTS rows without a date were skipped",
                            count=len(undated), examples=undated[:8]))
    if no_source:
        issues.append(Issue("warning", TAB_COSTS, "no_source", "COSTS rows with a cost but no Source were skipped",
                            count=len(no_source), examples=no_source[:8]))
    df = _frame(rows, COSTS_FRAME, ("date",))
    stats.kept = len(df)
    return df, stats, issues


def clean_revenues(tr: TabRows, start: date) -> tuple[pd.DataFrame, TabStats, list[Issue]]:
    stats, bad, rows, undated = TabStats(blank_rows=tr.blank_rows), _Bad(TAB_REVENUES), [], []
    text_fields = ("address", "source", "exit", "agent", "fus", "acq", "dispo", "dispo_lm")
    for rec in tr.records:
        r = rec["sheet_row"]
        try:
            d = to_datetime(rec.get("date"))
        except CellError as e:
            bad.add(r, "Date Closed", e)
            continue
        texts = {f: to_text(rec.get(f)).strip() if f != "source" else to_text(rec.get(f)) for f in text_fields}
        if all(is_blank(v) for v in texts.values()) and is_blank(rec.get("revenue")):
            stats.blank_rows += 1
            continue
        stats.rows_with_content += 1
        if d is None:
            undated.append(f"row {r}: {texts['address'] or '(no address)'}")
            continue
        if d.date() < start:
            stats.before_start += 1
            continue
        try:
            rev = to_money(rec.get("revenue"))
        except CellError as e:
            bad.add(r, "Revenue", e)
            continue
        rows.append({"date": d, "month": Month.of(d).key, **texts, "addr_key": addr_key(texts["address"]),
                     "revenue": rev or 0.0, "revenue_blank": rev is None, "sheet_row": r})
    issues = bad.issue()
    if undated:
        issues.append(Issue("warning", TAB_REVENUES, "undated_rows",
                            "REVENUES rows without a Date Closed were skipped",
                            count=len(undated), examples=undated[:8]))
    df = _frame(rows, REVENUES_FRAME, ("date",))
    stats.kept = len(df)
    return df, stats, issues


def clean_kpis(
    tr: TabRows, links: dict[int, str], start: date
) -> tuple[pd.DataFrame, pd.DataFrame, TabStats, BlankKpiDates, list[Issue]]:
    """KPI events counted by their trigger Date (blank Date = not triggered yet), plus the Lead rows.

    Lead rows are also returned as their own frame, counted by Date Created (All Leads): on a Lead row,
    Date is the Quality-change date, so a blank Date means the lead is still Pending.
    """
    stats, bad, rows, blank = TabStats(blank_rows=tr.blank_rows), _Bad(TAB_KPIS), [], BlankKpiDates()
    leads: list[dict] = []
    bad_created, lead_no_created = 0, []
    for rec in tr.records:
        r = rec["sheet_row"]
        try:
            d = to_datetime(rec.get("date"))
        except CellError as e:
            bad.add(r, "Date", e)
            continue
        try:
            created = to_datetime(rec.get("created"))
        except CellError:
            created, bad_created = None, bad_created + 1
        kpi, quality = canonical_kpi(to_text(rec.get("kpi")).strip()), to_text(rec.get("quality")).strip()
        stats.rows_with_content += 1
        addr = addr_key(to_text(rec.get("address")))
        common = {
            "quality": quality, "source": to_text(rec.get("source")), "acq": to_text(rec.get("acq")).strip(),
            "fus": to_text(rec.get("fus")).strip(), "lead_agent": to_text(rec.get("lead_agent")).strip(),
            "addr_key": addr, "lead_key": lead_key(links.get(r, "")) or (f"addr:{addr}" if addr else ""),
            "sheet_row": r,
        }
        if kpi == LEAD_KPI:
            if created is None:
                lead_no_created.append(f"row {r}")
            elif created.date() >= start:
                leads.append({"created": created, "month": Month.of(created).key, "date": d, **common})
        if d is None:
            blank.count += 1
            blank.by_quality[quality or "(blank)"] += 1
            blank.by_kpi[kpi or "(blank)"] += 1
            if created is not None and created.date() >= start:
                blank.created_since_start += 1
                if kpi == LEAD_KPI:
                    blank.leads_counted += 1
            continue
        if d.date() < start:
            stats.before_start += 1
            continue
        rows.append({"date": d, "month": Month.of(d).key, "created": created, "kpi": kpi,
                     "stage": to_text(rec.get("stage")).strip(), **common})
    issues = bad.issue()
    if bad_created:
        issues.append(Issue("info", TAB_KPIS, "bad_created", "KPIs: unreadable Date Created values", count=bad_created,
                            detail="Lead rows need Date Created to be counted in All Leads."))
    if lead_no_created:
        issues.append(Issue("warning", TAB_KPIS, "lead_no_created",
                            "KPIs: Lead rows without a Date Created (not counted in All Leads)",
                            count=len(lead_no_created), examples=lead_no_created[:8]))
    df = _frame(rows, KPIS_FRAME, ("date", "created"))
    stats.kept = len(df)
    return df, _frame(leads, LEADS_FRAME, ("created", "date")), stats, blank, issues


def links_by_row(values: list[list]) -> dict[int, str]:
    """Column M (GHL Link) by sheet row, header skipped. Used only to derive lead_key."""
    return {i: to_text(row[0]) for i, row in enumerate(values[1:], start=2) if row and not is_blank(row[0])}
