"""The deals behind a revenue number: REVENUES rows (every row is a deal) for some months, optionally one exit strategy
and one source. Follow Up = sources not on the projection, as everywhere else."""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from projection.data.load import Dataset
from projection.metrics.core import in_months
from projection.model import FOLLOW_UP, QuarterProjection
from projection.periods import Month

COLUMNS = {"date": "Date Closed", "address": "Address", "source": "Source", "exit": "Exit Strategy",
           "revenue": "Revenue", "acq": "ACQ", "fus": "FUS", "dispo": "DISPO", "dispo_lm": "DISPO LM",
           "agent": "AGENT"}


def deal_list(ds: Dataset, months: Iterable[Month], p: QuarterProjection | None = None, exit_: str | None = None,
              source: str | None = None) -> pd.DataFrame:
    """One row per deal, newest first, with the sheet's column names."""
    r = in_months(ds.revenues, months)
    if exit_ is not None:
        r = r[r["exit"] == exit_]
    if source == FOLLOW_UP and p is not None:
        r = r[~r["source"].isin(p.projected_sources())]
    elif source is not None:
        r = r[r["source"] == source]
    out = r.reindex(columns=list(COLUMNS)).sort_values("date", ascending=False).rename(columns=COLUMNS)
    out["Date Closed"] = pd.to_datetime(out["Date Closed"]).dt.date
    return out.reset_index(drop=True)
